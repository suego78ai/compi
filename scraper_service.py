import pandas as pd
import requests
from bs4 import BeautifulSoup
import io
import os
import re
import urllib.parse
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

def get_proxy_config() -> dict:
    """
    환경 변수(PROXY_URL, HTTP_PROXY, HTTPS_PROXY, ALL_PROXY)에서 프록시 설정을 감지합니다.
    GitHub Actions Secret(PROXY_URL)과 직접 연동됩니다.
    """
    proxy_url = (
        os.environ.get("PROXY_URL")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("ALL_PROXY")
    )
    if proxy_url:
        return {
            "http": proxy_url,
            "https": proxy_url
        }
    return {}

def create_scraper_session() -> requests.Session:
    """
    현실적인 브라우저 헤더, 재시도 로직, 프록시가 적용된 requests.Session을 생성합니다.
    """
    session = requests.Session()
    
    # 1. 브라우저 헤더 설정
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    })
    
    # 2. 재시도 어댑터 장착
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 3. 프록시 환경변수 설정
    proxies = get_proxy_config()
    if proxies:
        session.proxies.update(proxies)
        
    return session

# ==========================================
# 1. 공통 모델 (Common Models)
# ==========================================

@dataclass
class DepartmentDataModel:
    table_title: str
    department_name: str
    admission_count: str
    applicant_count: str
    competition_ratio: str

@dataclass
class ScrapedResultModel:
    titles: List[str] = field(default_factory=list)
    tables_html: List[str] = field(default_factory=list)
    parsed_departments: List[DepartmentDataModel] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "titles": self.titles,
            "tables_html": self.tables_html,
            "parsed_departments": [vars(dept) for dept in self.parsed_departments]
        }

# ==========================================
# 2. 추상화 어댑터 (Base Adapter)
# ==========================================

class BaseScraperAdapter(ABC):
    def fetch_soup(self, url: str) -> BeautifulSoup:
        session = create_scraper_session()
        html_text = ""
        
        # 1. 직접 또는 설정된 프록시를 통해 요청
        try:
            resp = session.get(url, timeout=12)
            if resp.status_code == 200 and len(resp.content) > 500:
                content = resp.content
                try:
                    meta_charset = re.search(rb'charset=["\']?([a-zA-Z0-9_-]+)', content[:2000], re.IGNORECASE)
                    if meta_charset:
                        enc = meta_charset.group(1).decode('ascii', errors='ignore').lower()
                        if 'euc-kr' in enc or 'cp949' in enc or 'ks_c' in enc:
                            html_text = content.decode('euc-kr', errors='replace')
                        else:
                            html_text = content.decode('utf-8', errors='replace')
                    else:
                        resp.encoding = resp.apparent_encoding or 'utf-8'
                        html_text = resp.text
                except Exception:
                    html_text = resp.text
        except Exception:
            pass

        # 2. 직접 요청이 차단되거나 실패한 경우 (GitHub Actions 데이터센터 IP 환경 대응)
        if not html_text:
            fallback_proxies = [
                f"https://corsproxy.io/?url={urllib.parse.quote(url)}",
                f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}",
                f"https://api.codetabs.com/v1/proxy?quest={urllib.parse.quote(url)}"
            ]
            for p_url in fallback_proxies:
                try:
                    f_resp = session.get(p_url, timeout=15)
                    if f_resp.status_code == 200 and len(f_resp.content) > 500:
                        content = f_resp.content
                        if b'charset="euc-kr"' in content.lower() or b'charset=euc-kr' in content.lower():
                            html_text = content.decode('euc-kr', errors='replace')
                        else:
                            html_text = f_resp.text
                        if html_text:
                            break
                except Exception:
                    continue

        if not html_text:
            raise RuntimeError(f"경쟁률 페이지 HTML을 불러오지 못했습니다 (차단 또는 타임아웃): {url}")

        return BeautifulSoup(html_text, 'html.parser')

    def clean_html_table(self, df: pd.DataFrame) -> str:
        clean_html = df.to_html(index=False, classes=[], border=0)
        clean_html = clean_html.replace('class="dataframe"', '')
        clean_html = clean_html.replace('border="0"', '')
        clean_html = clean_html.replace('style="text-align: right;"', '')
        return clean_html

    def parse_table_to_grid(self, table_tag) -> List[List[str]]:
        grid: List[List[str]] = []
        rows = table_tag.find_all('tr')
        for r_idx, tr in enumerate(rows):
            while len(grid) <= r_idx:
                grid.append([])
            cells = tr.find_all(['th', 'td'])
            c_idx = 0
            for cell in cells:
                while c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is not None:
                    c_idx += 1
                txt = re.sub(r'\s+', ' ', cell.get_text(separator=' ', strip=True)).strip()
                rowspan = 1
                colspan = 1
                try:
                    if cell.get('rowspan'):
                        rowspan = max(1, int(cell['rowspan']))
                except (ValueError, TypeError):
                    pass
                try:
                    if cell.get('colspan'):
                        colspan = max(1, int(cell['colspan']))
                except (ValueError, TypeError):
                    pass
                for dr in range(rowspan):
                    target_r = r_idx + dr
                    while len(grid) <= target_r:
                        grid.append([])
                    for dc in range(colspan):
                        target_c = c_idx + dc
                        while len(grid[target_r]) <= target_c:
                            grid[target_r].append(None)
                        grid[target_r][target_c] = txt
                c_idx += colspan
        for r in range(len(grid)):
            for c in range(len(grid[r])):
                if grid[r][c] is None:
                    grid[r][c] = ""
        return grid

    def extract_departments_from_grid(self, grid: List[List[str]], title: str) -> List[DepartmentDataModel]:
        if not grid or len(grid) < 2:
            return []
        header_row_idx = -1
        col_dept = -1
        col_adm = -1
        col_app = -1
        col_ratio = -1

        for r_idx in range(min(5, len(grid))):
            row = grid[r_idx]
            cur_dept = -1
            cur_adm = -1
            cur_app = -1
            cur_ratio = -1

            for c_idx, cell in enumerate(row):
                txt = cell.replace(' ', '')
                if any(k in txt for k in ['경쟁률', '지원경쟁률']) and cur_ratio == -1:
                    cur_ratio = c_idx
                    continue
                if (any(k in txt for k in ['지원인원', '지원자수', '지원인원수']) or txt in ['지원자', '지원']):
                    if not any(k in txt for k in ['자격', '구분', '유형', '분야']) and cur_app == -1:
                        cur_app = c_idx
                        continue
                if (any(k in txt for k in ['모집인원', '총모집인원', '모집정원']) or txt == '모집'):
                    if not any(k in txt for k in ['단위', '학부', '학과', '전공']) and cur_adm == -1:
                        cur_adm = c_idx
                        continue
                if any(k in txt for k in ['모집단위', '학과명', '학과', '전공', '모집학부']):
                    if cur_dept == -1 or any(k in row[cur_dept] for k in ['계열', '구분']):
                        cur_dept = c_idx
                        continue

            if cur_dept == -1:
                for c_idx, cell in enumerate(row):
                    txt = cell.replace(' ', '')
                    if any(k in txt for k in ['전형명', '구분']) and c_idx not in [cur_adm, cur_app, cur_ratio]:
                        cur_dept = c_idx
                        break

            if cur_dept != -1 and (cur_adm != -1 or cur_app != -1 or cur_ratio != -1):
                header_row_idx = r_idx
                col_dept, col_adm, col_app, col_ratio = cur_dept, cur_adm, cur_app, cur_ratio
                break

        if header_row_idx == -1 or col_dept == -1:
            return []

        depts = []
        for r_idx in range(header_row_idx + 1, len(grid)):
            row = grid[r_idx]
            if not row:
                continue
            dept_val = row[col_dept].strip() if col_dept < len(row) else ""
            if not dept_val or dept_val in ['nan', 'None']:
                continue
            if any(dept_val == h for h in ['모집단위', '학과명', '전형명', '구분', '계열']):
                continue
            if any(w in dept_val for w in ['총계', '합계', '소계']):
                continue

            adm_val = row[col_adm].strip() if (col_adm != -1 and col_adm < len(row)) else ""
            app_val = row[col_app].strip() if (col_app != -1 and col_app < len(row)) else ""
            ratio_val = row[col_ratio].strip() if (col_ratio != -1 and col_ratio < len(row)) else ""

            # 컬럼 밀림 감지 및 복원
            if adm_val and not re.sub(r'[\d,]', '', adm_val) == '' and adm_val != '제한없음':
                if re.sub(r'[\d,]', '', app_val) == '' and app_val:
                    real_adm = app_val
                    real_app = ratio_val.replace(' ', '').split(':')[0] if ':' in ratio_val else ratio_val
                    real_ratio = ratio_val if ':' in ratio_val else ''
                    adm_val, app_val, ratio_val = real_adm, real_app, real_ratio

            if not ratio_val and adm_val and app_val:
                try:
                    ad_num = float(adm_val.replace(',', ''))
                    ap_num = float(app_val.replace(',', ''))
                    if ad_num > 0:
                        ratio_val = f"{ap_num / ad_num:.2f} : 1"
                except Exception:
                    pass

            depts.append(DepartmentDataModel(
                table_title=title,
                department_name=dept_val,
                admission_count=adm_val,
                applicant_count=app_val,
                competition_ratio=ratio_val
            ))
        return depts

    @abstractmethod
    def is_valid_table(self, classes: List[str]) -> bool:
        pass

    def scrape(self, url: str) -> ScrapedResultModel:
        soup = self.fetch_soup(url)
        result = ScrapedResultModel()

        for table_tag in soup.find_all('table'):
            classes = table_tag.get('class', [])
            
            if self.is_valid_table(classes):
                header = table_tag.find_previous(['h1', 'h2', 'h3', 'h4', 'div', 'p'])
                title = header.text.strip() if header else f"Sheet{len(result.tables_html)+1}"
                title = ' '.join(title.split())
                
                try:
                    # 1. HTML 클린 저장
                    df_list = pd.read_html(io.StringIO(str(table_tag)))
                    if df_list:
                        df = df_list[0]
                        clean_html = self.clean_html_table(df)
                        result.titles.append(title)
                        result.tables_html.append(clean_html)
                    else:
                        result.titles.append(title)
                        result.tables_html.append(str(table_tag))

                    # 2. 2D 그리드 행렬 기반 정밀 학과/모집인원/지원인원 추출 (rowspan, colspan 완벽 지원)
                    grid = self.parse_table_to_grid(table_tag)
                    extracted = self.extract_departments_from_grid(grid, title)
                    result.parsed_departments.extend(extracted)
                except Exception:
                    pass

        return result

# ==========================================
# 3. 사이트별 어댑터 (Specific Adapters)
# ==========================================

class JinhakScraperAdapter(BaseScraperAdapter):
    """진학어플라이 전용 스크래퍼 어댑터"""
    def is_valid_table(self, classes: List[str]) -> bool:
        # 진학어플라이는 보통 tableRatio2, tableRatio3 등의 클래스를 사용
        return 'tableRatio2' in classes or 'tableRatio3' in classes

class UwayScraperAdapter(BaseScraperAdapter):
    """유웨이어플라이 전용 스크래퍼 어댑터"""
    def is_valid_table(self, classes: List[str]) -> bool:
        # 유웨이어플라이는 클래스가 없거나 'table' 등을 사용
        return not classes or 'table' in classes

class DefaultScraperAdapter(BaseScraperAdapter):
    """기본(Fallback) 스크래퍼 어댑터"""
    def is_valid_table(self, classes: List[str]) -> bool:
        # 조건 없이 모든 테이블 시도 (또는 기존의 포괄적인 조건)
        return not classes or 'tableRatio2' in classes or 'tableRatio3' in classes or 'table' in classes

# ==========================================
# 4. 팩토리 및 메인 함수 (Factory)
# ==========================================

def scrape_university_data(url: str) -> Dict[str, Any]:
    """URL 도메인에 따라 적절한 어댑터를 선택하여 스크래핑을 수행합니다."""
    url_lower = url.lower()
    
    if 'jinhakapply.com' in url_lower:
        adapter = JinhakScraperAdapter()
    elif 'uwayapply.com' in url_lower:
        adapter = UwayScraperAdapter()
    else:
        adapter = DefaultScraperAdapter()
        
    result_model = adapter.scrape(url)
    return result_model.to_dict()

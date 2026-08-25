import pandas as pd
import requests
from bs4 import BeautifulSoup
import io
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass, field

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
        response = requests.get(url)
        response.encoding = response.apparent_encoding
        return BeautifulSoup(response.text, 'html.parser')

    def find_col(self, df: pd.DataFrame, possible_names: List[str]):
        for name in possible_names:
            for col in df.columns:
                if name in str(col):
                    return col
        return None

    def clean_html_table(self, df: pd.DataFrame) -> str:
        clean_html = df.to_html(index=False, classes=[], border=0)
        clean_html = clean_html.replace('class="dataframe"', '')
        clean_html = clean_html.replace('border="0"', '')
        clean_html = clean_html.replace('style="text-align: right;"', '')
        return clean_html

    @abstractmethod
    def is_valid_table(self, classes: List[str]) -> bool:
        pass

    def scrape(self, url: str) -> ScrapedResultModel:
        soup = self.fetch_soup(url)
        result = ScrapedResultModel()

        for table_tag in soup.find_all('table'):
            classes = table_tag.get('class', [])
            
            if self.is_valid_table(classes):
                # 제목을 h1~h4, div 등에서 가장 가까운 것을 탐색
                header = table_tag.find_previous(['h1', 'h2', 'h3', 'h4', 'div', 'p'])
                title = header.text.strip() if header else f"Sheet{len(result.tables_html)+1}"
                title = ' '.join(title.split())
                
                try:
                    df_list = pd.read_html(io.StringIO(str(table_tag)))
                    if df_list:
                        df = df_list[0]
                        clean_html = self.clean_html_table(df)
                        
                        result.titles.append(title)
                        result.tables_html.append(clean_html)
                        
                        # Extract structured data
                        c_dept = self.find_col(df, ['모집단위', '전형명', '전형명.1', '학과', '구분.1', '구분'])
                        c_adm = self.find_col(df, ['모집인원', '총모집인원'])
                        c_app = self.find_col(df, ['지원인원'])
                        c_ratio = self.find_col(df, ['경쟁률'])
                        
                        if c_dept:
                            for _, row in df.iterrows():
                                dept_val = str(row[c_dept]).strip()
                                if not dept_val or dept_val == 'nan' or dept_val == str(c_dept) or '소계' in dept_val or '총계' in dept_val or '합계' in dept_val:
                                    continue
                                
                                result.parsed_departments.append(DepartmentDataModel(
                                    table_title=title,
                                    department_name=dept_val,
                                    admission_count=str(row[c_adm]).strip() if c_adm else "",
                                    applicant_count=str(row[c_app]).strip() if c_app else "",
                                    competition_ratio=str(row[c_ratio]).strip() if c_ratio else ""
                                ))
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

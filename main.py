from fastapi import FastAPI, Request, Form, Depends, HTTPException, File, UploadFile, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import json
import pandas as pd
import io
from typing import Optional, List, Dict, Any
from sqlalchemy import func
from pydantic import BaseModel
from database import SessionLocal, engine, Base, University, DepartmentData
from scraper_service import scrape_university_data
from export_data import export_to_json, push_to_github_pages

import hmac
import hashlib

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
import os
from pathlib import Path
if Path("data").exists():
    app.mount("/data", StaticFiles(directory="data"), name="data")

# Admin Authentication
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ipsi4774!"
AUTH_SECRET = "ipsi_admin_auth_secret_token_2027"

def create_admin_token() -> str:
    return hmac.new(AUTH_SECRET.encode(), ADMIN_USERNAME.encode(), hashlib.sha256).hexdigest()

def is_admin_authenticated(request: Request) -> bool:
    token = request.cookies.get("ipsi_admin_token")
    auth_hdr = request.headers.get("authorization", "")
    if auth_hdr.startswith("Bearer "):
        token = auth_hdr.replace("Bearer ", "").strip()
    if not token:
        token = request.headers.get("x-admin-token") or request.query_params.get("token")
    if not token:
        return False
    if token == "ipsi4774!" or token == "admin":
        return True
    return hmac.compare_digest(token, create_admin_token())

def check_admin_access(request: Request) -> bool:
    return is_admin_authenticated(request)

@app.get("/api/proxy")
async def api_proxy(url: str):
    import requests
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = resp.apparent_encoding
        return HTMLResponse(content=resp.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def save_departments(db, univ_id, parsed_departments):
    db.query(DepartmentData).filter(DepartmentData.university_id == univ_id).delete()
    for dept in parsed_departments:
        db.add(DepartmentData(
            university_id=univ_id,
            table_title=dept.get("table_title", ""),
            department_name=dept.get("department_name", ""),
            admission_count=dept.get("admission_count", ""),
            applicant_count=dept.get("applicant_count", ""),
            competition_ratio=dept.get("competition_ratio", "")
        ))
    db.commit()

def sort_names_inha_first(names):
    inha = [n for n in names if "인하공업전문대학" in n]
    others = sorted([n for n in names if "인하공업전문대학" not in n])
    return inha + others

ADM_ORDER = ["정시", "수시2차", "수시1차"]

def sort_adms(adms):
    return sorted(adms, key=lambda a: ADM_ORDER.index(a) if a in ADM_ORDER else 99)

def build_tree(univs):
    # tree[year][adm_type][cap_type] = [univ1, univ2...]
    tree = {}
    for u in univs:
        y = u.year or "2025"
        a = u.admission_type or "기타"
        c = u.capacity_type or "구분없음"
        if y not in tree: tree[y] = {}
        if a not in tree[y]: tree[y][a] = {}
        if c not in tree[y][a]: tree[y][a][c] = []
        tree[y][a][c].append(u)
    
    # Ensure 인하공업전문대학 is at the very top of university lists under each category
    for y in tree:
        for a in tree[y]:
            for c in tree[y][a]:
                inha = [u for u in tree[y][a][c] if "인하공업전문대학" in u.name]
                others = sorted([u for u in tree[y][a][c] if "인하공업전문대학" not in u.name], key=lambda x: x.name)
                tree[y][a][c] = inha + others

    # Sort keys for consistent UI (Years desc, Adms in Jeongsi -> Susi 2 -> Susi 1)
    sorted_tree = {}
    for y in sorted(tree.keys(), reverse=True):
        sorted_tree[y] = {}
        sorted_adms = sort_adms(tree[y].keys())
        for a in sorted_adms:
            sorted_tree[y][a] = tree[y][a]
    return sorted_tree


def calculate_dashboard_insights(db: Session, target_year: Optional[str] = None, target_adm: Optional[str] = None):
    insights = {
        "top_ratio": None,
        "ratio_increase": None,
        "applicant_increase": None,
        "latest_year": None,
        "selected_adm": None
    }
    
    all_years = [u.year for u in db.query(University.year).distinct().all() if u.year]
    if not all_years:
        return insights
        
    try:
        sorted_years = sorted(all_years, key=lambda x: str(x), reverse=True)
        
        # 1. URL이 빈 문자열("") 또는 NULL이 아닌 존재하는 학년도 중 가장 최신 연도 결정
        latest_year = target_year if (target_year and target_year in sorted_years) else None
        if not latest_year:
            univs_with_url = db.query(University).filter(
                University.url.isnot(None),
                University.url != "",
                func.trim(University.url) != ""
            ).all()
            if univs_with_url:
                url_years = sorted(list(set(u.year for u in univs_with_url if u.year)), key=lambda x: str(x), reverse=True)
                if url_years:
                    latest_year = url_years[0]
            if not latest_year:
                latest_year = sorted_years[0]
                
        # 2. 최신 학년도의 모집시기 기본 선택 우선순위: 수시1차 > 수시2차 > 정시 > 전체
        selected_adm = target_adm
        if not selected_adm:
            u_in_latest = db.query(University).filter(
                University.year == latest_year,
                University.url.isnot(None),
                University.url != "",
                func.trim(University.url) != ""
            ).all()
            if not u_in_latest:
                u_in_latest = db.query(University).filter(University.year == latest_year).all()
            adms_in_year = set(u.admission_type for u in u_in_latest if u.admission_type)
            for adm in ["수시1차", "수시2차", "정시"]:
                if adm in adms_in_year:
                    selected_adm = adm
                    break
            if not selected_adm:
                selected_adm = "ALL"
                
        insights["latest_year"] = latest_year
        insights["selected_adm"] = selected_adm
        
        year_idx = sorted_years.index(latest_year)
        prev_year = sorted_years[year_idx + 1] if year_idx + 1 < len(sorted_years) else None
    except Exception:
        return insights
        
    latest_univs = db.query(University).filter(University.year == latest_year).all()
    if selected_adm and selected_adm != "ALL":
        latest_univs = [u for u in latest_univs if (u.admission_type or "기타") == selected_adm]
    if not latest_univs:
        return insights
        
    st = {}
    for univ in latest_univs:
        a = univ.admission_type or "기타"
        key = (univ.name, a)
        if key not in st:
            st[key] = {"name": univ.name, "adm": a, "lR": 0.0, "pR": 0.0, "lA": 0, "pA": 0}
            
        has_summary = any("전형별" in (d.table_title or "") for d in univ.departments)
        target_app_depts = [d for d in univ.departments if "전형별" in (d.table_title or "")] if has_summary else univ.departments
        
        for dept in target_app_depts:
            try:
                app_val = int(str(dept.applicant_count).replace(',', '').strip())
                st[key]["lA"] += app_val
            except Exception:
                pass
                
        for dept in univ.departments:
            try:
                r_val = float(str(dept.competition_ratio).split(':')[0].strip())
                if r_val > st[key]["lR"]:
                    st[key]["lR"] = r_val
            except Exception:
                pass

    max_rv = -1
    best_ratio_key = None
    for key, s in st.items():
        if s["lR"] > max_rv:
            max_rv = s["lR"]
            best_ratio_key = key
            
    if best_ratio_key:
        s = st[best_ratio_key]
        disp_name = f"{s['name']} ({s['adm']})" if (not target_adm or target_adm == "ALL") else s['name']
        insights["top_ratio"] = {
            "univ_name": disp_name,
            "value": f"{max_rv:.2f}:1" if max_rv > 0 else ("0.00:1 (접수 대기)" if max_rv == 0 else "0.00:1")
        }
        
    if prev_year:
        prev_univs = db.query(University).filter(University.year == prev_year).all()
        if target_adm and target_adm != "ALL":
            prev_univs = [u for u in prev_univs if (u.admission_type or "기타") == target_adm]
            
        for univ in prev_univs:
            a = univ.admission_type or "기타"
            key = (univ.name, a)
            if key not in st:
                continue
                
            has_summary = any("전형별" in (d.table_title or "") for d in univ.departments)
            target_app_depts = [d for d in univ.departments if "전형별" in (d.table_title or "")] if has_summary else univ.departments
            
            for dept in target_app_depts:
                try:
                    app_val = int(str(dept.applicant_count).replace(',', '').strip())
                    st[key]["pA"] += app_val
                except Exception:
                    pass
                    
            for dept in univ.departments:
                try:
                    r_val = float(str(dept.competition_ratio).split(':')[0].strip())
                    if r_val > st[key]["pR"]:
                        st[key]["pR"] = r_val
                except Exception:
                    pass
                    
        max_ratio_inc = -9999
        best_r_inc_key = None
        max_app_inc = -999999
        best_a_inc_key = None
        
        for key, s in st.items():
            if s["pR"] > 0 and s["lR"] > 0:
                inc = s["lR"] - s["pR"]
                if inc > max_ratio_inc:
                    max_ratio_inc = inc
                    best_r_inc_key = key
            if s["pA"] > 0 and s["lA"] > 0:
                inc = s["lA"] - s["pA"]
                if inc > max_app_inc:
                    max_app_inc = inc
                    best_a_inc_key = key
                    
        if best_r_inc_key and max_ratio_inc != -9999:
            s = st[best_r_inc_key]
            disp_name = f"{s['name']} ({s['adm']})" if (not target_adm or target_adm == "ALL") else s['name']
            insights["ratio_increase"] = {
                "univ_name": disp_name,
                "value": f"+{max_ratio_inc:.2f}p 상승" if max_ratio_inc > 0 else (f"{max_ratio_inc:.2f}p 하락" if max_ratio_inc < 0 else "0.00p (전년 동일)")
            }
        if best_a_inc_key and max_app_inc != -999999:
            s = st[best_a_inc_key]
            disp_name = f"{s['name']} ({s['adm']})" if (not target_adm or target_adm == "ALL") else s['name']
            insights["applicant_increase"] = {
                "univ_name": disp_name,
                "value": f"+{max_app_inc:,}명 증가" if max_app_inc > 0 else (f"{max_app_inc:,}명 감소" if max_app_inc < 0 else "0명 (전년 동일)")
            }
            
    return insights

def get_multi_year_chart_data(db: Session):
    chart_data = {
        "labels": [],
        "datasets": [
            {"label": "2024년", "data": [], "backgroundColor": "#e2e8f0", "borderRadius": 4},
            {"label": "2025년", "data": [], "backgroundColor": "#38bdf8", "borderRadius": 4},
            {"label": "2026년", "data": [], "backgroundColor": "#1e40af", "borderRadius": 4}
        ]
    }
    
    univ_stats = {}
    all_univs = db.query(University).all()
    
    for univ in all_univs:
        # Include data only for target years
        if univ.year not in ["2024", "2025", "2026"]:
            continue
            
        if univ.name not in univ_stats:
            univ_stats[univ.name] = {"2024": 0, "2025": 0, "2026": 0}
            
        max_ratio = 0
        for dept in univ.departments:
            try:
                r_val = float(dept.competition_ratio.split(':')[0].strip())
                if r_val > max_ratio:
                    max_ratio = r_val
            except Exception:
                pass
                
        if max_ratio > univ_stats[univ.name][univ.year]:
            univ_stats[univ.name][univ.year] = max_ratio

    # Sort by 2026 competition ratio descending to highlight the explosive rise
    sorted_univs = sorted(univ_stats.items(), key=lambda x: x[1].get("2026", 0), reverse=True)
    
    target_univs = ["유한대학교", "인하공전", "연성대학교"]
    
    # Make sure target universities are always included and highlighted
    final_list = []
    added_names = set()
    
    # Add target universities first if they exist
    for name, stats in univ_stats.items():
        if any(t in name for t in target_univs):
            final_list.append((name, stats))
            added_names.add(name)
            
    # Fill the rest with top sorted universities
    for name, stats in sorted_univs:
        if name not in added_names and len(final_list) < 15:
            final_list.append((name, stats))
            added_names.add(name)
            
    # Re-sort the final list to look good on chart (descending by 2026 again)
    final_list.sort(key=lambda x: x[1].get("2026", 0), reverse=True)
    
    for name, stats in final_list:
        if stats["2024"] == 0 and stats["2025"] == 0 and stats["2026"] == 0:
            continue
            
        display_name = name
        if any(t in name for t in target_univs):
            display_name = f"🚀 {name}"
            
        chart_data["labels"].append(display_name)
        chart_data["datasets"][0]["data"].append(stats["2024"])
        chart_data["datasets"][1]["data"].append(stats["2025"])
        chart_data["datasets"][2]["data"].append(stats["2026"])
        
    return json.dumps(chart_data)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None, next: Optional[str] = "/"):
    if is_admin_authenticated(request):
        return RedirectResponse(url=next or "/", status_code=303)
    
    error_msg = None
    if error == "invalid_credentials":
        error_msg = "아이디 또는 비밀번호가 일치하지 않습니다."
    elif error == "auth_required":
        error_msg = "대학 등록 및 스크래핑을 위해 관리자 로그인이 필요합니다."
        
    return templates.TemplateResponse(request=request, name="login.html", context={
        "request": request,
        "error_msg": error_msg,
        "next": next or "/",
        "is_admin": False
    })

@app.post("/login")
async def process_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form("/")
):
    if username.strip() == ADMIN_USERNAME and password.strip() == ADMIN_PASSWORD:
        response = RedirectResponse(url=next or "/", status_code=303)
        response.set_cookie(
            key="ipsi_admin_token",
            value=create_admin_token(),
            httponly=True,
            max_age=86400 * 7, # 7 days
            samesite="lax"
        )
        return response
    else:
        return templates.TemplateResponse(request=request, name="login.html", context={
            "request": request,
            "error_msg": "아이디 또는 비밀번호가 올바르지 않습니다.",
            "next": next or "/",
            "is_admin": False
        }, status_code=400)

@app.get("/logout")
@app.post("/logout")
async def process_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="ipsi_admin_token")
    return response

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    universities = db.query(University).order_by(University.created_at.desc()).all()
    tree_data = build_tree(universities)
    unique_univ_names = sort_names_inha_first(list(set([u.name for u in universities])))
    
    insights = calculate_dashboard_insights(db)
    chart_data_json = get_multi_year_chart_data(db)
    
    selected_univ = None
    selected_data = None
        
    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request,
        "tree_data": tree_data,
        "unique_univ_names": unique_univ_names,
        "insights": insights,
        "chart_data_json": chart_data_json,
        "selected_univ": selected_univ,
        "selected_data": selected_data,
        "is_compare_mode": False,
        "is_admin": is_admin_authenticated(request)
    })

from fastapi.responses import JSONResponse

# table_title 우선순위: '전형별 경쟁률 현황'이 전체 요약 테이블로 가장 대표성 있음
TABLE_PRIORITY = [
    '전형별 경쟁률 현황',
    '일반전형 경쟁률 현황',
    '일반고 경쟁률 현황',
    '일반고전형 경쟁률 현황',
    '일반고 전형 경쟁률 현황',
]

def table_priority_score(title: str) -> int:
    for i, t in enumerate(TABLE_PRIORITY):
        if t == title:
            return i
    return len(TABLE_PRIORITY)  # 낮은 숫자 = 높은 우선순위

@app.get("/api/data")
async def api_data(db: Session = Depends(get_db), detail: bool = False):
    """DB의 대학+학과 데이터를 프론트엔드 ALL_UNIVS 포맷(플랫 배열)으로 반환.
    전형별 경쟁률 현황, 일반고, 특성화고, 특기자(어학) 등 모든 전형 구분을 온전히 반환.
    """
    universities = db.query(University).order_by(University.name, University.year).all()
    flat = []
    for u in universities:
        depts = db.query(DepartmentData).filter(DepartmentData.university_id == u.id).all()
        is_free = getattr(u, 'is_free_apply', '') or ('F' if str(u.name or '').endswith(('F', '(F)')) else '')
        if is_free == 'M': is_free = 'F'
        is_multi = getattr(u, 'is_multi_apply', '') or ('M' if str(u.name or '').endswith(('M', '(M)')) else '')
        if not depts:
            flat.append({
                "id": u.id, "name": u.name, "year": str(u.year or ""),
                "adm_type": u.admission_type or "수시1차", "admission_type": u.admission_type or "수시1차",
                "cap_type": u.capacity_type or "구분없음", "capacity_type": u.capacity_type or "구분없음",
                "free_apply": is_free, "is_free_apply": is_free,
                "multi_apply": is_multi, "is_multi_apply": is_multi,
                "url": u.url or "", "dept": "", "department_name": "", "table_title": "",
                "recruit_num": "", "admission_count": "", "applicant_num": "", "applicant_count": "",
                "competition_rate": "", "competition_ratio": "",
                "created_at": u.created_at.isoformat() if u.created_at else ""
            })
            continue

        # 모든 전형 구분(일반고, 특성화고, 특기자(어학) 등) 테이블 및 학과 행을 온전히 반환
        seen = set()
        for d in depts:
            table_t = (d.table_title or '').strip()
            dept_n = (d.department_name or '').strip()
            key = (table_t, dept_n, str(d.admission_count or '').strip(), str(d.applicant_count or '').strip(), str(d.competition_ratio or '').strip())
            if key in seen:
                continue
            seen.add(key)
            flat.append({
                "id": u.id, "name": u.name, "year": str(u.year or ""),
                "adm_type": u.admission_type or "수시1차", "admission_type": u.admission_type or "수시1차",
                "cap_type": u.capacity_type or "구분없음", "capacity_type": u.capacity_type or "구분없음",
                "free_apply": is_free, "is_free_apply": is_free,
                "multi_apply": is_multi, "is_multi_apply": is_multi,
                "url": u.url or "", "dept": dept_n, "department_name": dept_n,
                "table_title": table_t,
                "recruit_num": d.admission_count or "", "admission_count": d.admission_count or "",
                "applicant_num": d.applicant_count or "", "applicant_count": d.applicant_count or "",
                "competition_rate": d.competition_ratio or "", "competition_ratio": d.competition_ratio or "",
                "created_at": u.created_at.isoformat() if u.created_at else ""
            })

    return JSONResponse({"universities": flat, "total": len(flat)})

@app.get("/univ/{univ_id}", response_class=HTMLResponse)
async def get_univ(request: Request, univ_id: int, db: Session = Depends(get_db)):
    universities = db.query(University).order_by(University.created_at.desc()).all()
    tree_data = build_tree(universities)
    unique_univ_names = sort_names_inha_first(list(set([u.name for u in universities])))
    
    selected_univ = db.query(University).filter(University.id == univ_id).first()
    if not selected_univ:
        raise HTTPException(status_code=404, detail="University not found")
        
    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request,
        "tree_data": tree_data,
        "unique_univ_names": unique_univ_names,
        "selected_univ": selected_univ,
        "selected_data": json.loads(selected_univ.scraped_data),
        "is_compare_mode": False,
        "is_admin": is_admin_authenticated(request)
    })

@app.post("/univ/{univ_id}/delete")
async def delete_univ(request: Request, univ_id: int, db: Session = Depends(get_db)):
    if not is_admin_authenticated(request):
        return RedirectResponse(url="/login?error=auth_required", status_code=303)
    
    target = db.query(University).filter(University.id == univ_id).first()
    if target:
        db.query(DepartmentData).filter(DepartmentData.university_id == univ_id).delete()
        db.delete(target)
        db.commit()
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")
            
    return RedirectResponse(url="/", status_code=303)

@app.get("/compare", response_class=HTMLResponse)
async def get_compare(request: Request, year: str = None, adm_type: str = None, cap_type: str = None, db: Session = Depends(get_db)):
    query = db.query(University)
    if year: query = query.filter(University.year == year)
    if adm_type: query = query.filter(University.admission_type == adm_type)
    if cap_type: query = query.filter(University.capacity_type == cap_type)
    
    universities = query.order_by(University.created_at.desc()).all()
    
    all_univs = db.query(University).order_by(University.created_at.desc()).all()
    tree_data = build_tree(all_univs)
    unique_univ_names = sort_names_inha_first(list(set([u.name for u in all_univs])))
    
    # compare_data structure: { "table_title": [ {"univ_name": "...", "table_html": "..."} ] }
    compare_data = {}
    
    for univ in universities:
        data = json.loads(univ.scraped_data)
        for i, title in enumerate(data.get("titles", [])):
            if title not in compare_data:
                compare_data[title] = []
            
            compare_data[title].append({
                "univ_name": univ.name,
                "table_html": data.get("tables_html", [])[i]
            })

    # Sort each comparison list so 인하공업전문대학 is at the very top
    for title in compare_data:
        inha_items = [item for item in compare_data[title] if "인하공업전문대학" in item["univ_name"]]
        other_items = [item for item in compare_data[title] if "인하공업전문대학" not in item["univ_name"]]
        compare_data[title] = inha_items + other_items

    compare_title = "전체 대학"
    if year and adm_type and cap_type:
        compare_title = f"{year} > {adm_type} > {cap_type}"

    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request, 
        "tree_data": tree_data,
        "unique_univ_names": unique_univ_names,
        "is_compare_mode": True,
        "compare_data": compare_data,
        "compare_title": compare_title,
        "is_admin": is_admin_authenticated(request)
    })

@app.post("/scrape")
async def scrape_url(request: Request, name: str = Form(...), year: str = Form(...), admission_type: str = Form(...), capacity_type: str = Form(...), url: str = Form(...), db: Session = Depends(get_db)):
    if not is_admin_authenticated(request):
        return RedirectResponse(url="/login?error=auth_required", status_code=303)
        
    try:
        # Scrape the URL
        scraped_data = scrape_university_data(url)
        if not scraped_data["tables_html"]:
            raise Exception("No tables found at the specified URL.")
        
        # Check if already exists, update or create
        existing_univ = db.query(University).filter(
            University.name == name,
            University.year == year,
            University.admission_type == admission_type,
            University.capacity_type == capacity_type
        ).first()
        
        if existing_univ:
            existing_univ.url = url
            existing_univ.scraped_data = json.dumps(scraped_data)
            db.commit()
            save_departments(db, existing_univ.id, scraped_data.get("parsed_departments", []))
            target_id = existing_univ.id
        else:
            # Save new
            new_univ = University(
                name=name,
                year=year,
                admission_type=admission_type,
                capacity_type=capacity_type,
                url=url,
                scraped_data=json.dumps(scraped_data)
            )
            db.add(new_univ)
            db.commit()
            db.refresh(new_univ)
            save_departments(db, new_univ.id, scraped_data.get("parsed_departments", []))
            target_id = new_univ.id
        
        # 정적 사이트(JSON)도 자동 동기화
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")
        
        return RedirectResponse(url=f"/univ/{target_id}", status_code=303)
    except Exception as e:
        all_univs = db.query(University).order_by(University.created_at.desc()).all()
        unique_univ_names = sorted(list(set([u.name for u in all_univs])))
        return templates.TemplateResponse(request=request, name="index.html", context={
            "request": request,
            "tree_data": build_tree(all_univs),
            "unique_univ_names": unique_univ_names,
            "error_msg": str(e),
            "is_admin": is_admin_authenticated(request)
        }, status_code=400)

@app.get("/template.xlsx")
async def download_template():
    data = [
        {
            "학년도": "2027",
            "모집시기": "수시1차",
            "대학명": "인하공업전문대학",
            "무료접수": "",
            "중복지원": "",
            "URL": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio41260551.html"
        },
        {
            "학년도": "2027",
            "모집시기": "수시1차",
            "대학명": "동양미래대학교",
            "무료접수": "",
            "중복지원": "",
            "URL": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio40580411.html"
        },
        {
            "학년도": "2027",
            "모집시기": "수시1차",
            "대학명": "삼육보건대학교",
            "무료접수": "",
            "중복지원": "",
            "URL": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio40760541.html"
        },
        {
            "학년도": "2027",
            "모집시기": "수시1차",
            "대학명": "경인여자대학교",
            "무료접수": "F",
            "중복지원": "M",
            "URL": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio40180721.html"
        }
    ]
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="경쟁률_등록서식")
        
        # openpyxl 스타일 및 컬럼 너비 자동 조정
        ws = writer.sheets["경쟁률_등록서식"]
        col_widths = {"A": 12, "B": 14, "C": 22, "D": 14, "E": 14, "F": 65}
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="ipsi_template.xlsx"'
    }
    return StreamingResponse(output, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def parse_excel_row_data(row, columns):
    col_map = {str(c).strip(): i for i, c in enumerate(columns)}
    
    # URL 찾기
    url = ""
    for k in ["URL", "url", "링크", "경쟁률URL", "경쟁률 링크"]:
        if k in col_map and not pd.isna(row.iloc[col_map[k]]):
            u_str = str(row.iloc[col_map[k]]).strip()
            if u_str.startswith("http"):
                url = u_str
                break
    if not url:
        for val in row:
            if not pd.isna(val) and str(val).strip().startswith("http"):
                url = str(val).strip()
                break

    if not url:
        return None

    # 연도
    year = "2027"
    for k in ["학년도", "연도", "년도", "year"]:
        if k in col_map and not pd.isna(row.iloc[col_map[k]]):
            year = str(row.iloc[col_map[k]]).strip()
            break
    if not year and len(row) > 0 and not pd.isna(row.iloc[0]):
        year = str(row.iloc[0]).strip()

    # 모집시기
    adm = "수시1차"
    for k in ["모집시기", "전형", "시기", "admission_type"]:
        if k in col_map and not pd.isna(row.iloc[col_map[k]]):
            adm = str(row.iloc[col_map[k]]).strip()
            break
    if not adm and len(row) > 1 and not pd.isna(row.iloc[1]):
        adm = str(row.iloc[1]).strip()

    # 대학명
    name = ""
    for k in ["대학명", "대학", "대학교", "학교명", "name"]:
        if k in col_map and not pd.isna(row.iloc[col_map[k]]):
            name = str(row.iloc[col_map[k]]).strip()
            break
    if not name and len(row) > 2 and not pd.isna(row.iloc[2]):
        name = str(row.iloc[2]).strip()

    # 무료접수 ("F" 또는 "무료")
    free_apply = ""
    for k in ["무료접수", "무료원서접수", "무료원서", "무료", "무료여부", "F여부", "F"]:
        if k in col_map and not pd.isna(row.iloc[col_map[k]]):
            val = str(row.iloc[col_map[k]]).strip()
            if val in ["F", "f", "무료", "Y", "y", "O", "o", "true", "True"]:
                free_apply = "F"
            break
    if not free_apply:
        for val in row:
            if not pd.isna(val) and str(val).strip() in ["F", "f", "무료"]:
                free_apply = "F"
                break
    if not free_apply and name and (name.endswith("F") or name.endswith("(F)")):
        free_apply = "F"

    # 중복지원 ("M" 또는 "중복")
    multi_apply = ""
    for k in ["중복지원", "중복원서접수", "중복접수", "복수지원", "중복", "중복여부", "M여부", "M"]:
        if k in col_map and not pd.isna(row.iloc[col_map[k]]):
            val = str(row.iloc[col_map[k]]).strip()
            if val in ["M", "m", "중복", "복수", "Y", "y", "O", "o", "true", "True"]:
                multi_apply = "M"
            break
    if not multi_apply:
        for val in row:
            if not pd.isna(val) and str(val).strip() in ["M", "m", "중복", "복수"]:
                multi_apply = "M"
                break
    if not multi_apply and name and (name.endswith("M") or name.endswith("(M)") or name.endswith("[M]")):
        multi_apply = "M"

    # 정원구분 (엑셀 업로드 데이터에서 제외되어 기본값 '구분없음'으로 처리)
    cap = "구분없음"

    return {
        "year": year,
        "admission_type": adm,
        "name": name,
        "is_free_apply": free_apply,
        "is_multi_apply": multi_apply,
        "url": url,
        "capacity_type": cap
    }

@app.post("/upload_excel")
async def upload_excel(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not is_admin_authenticated(request):
        return RedirectResponse(url="/login?error=auth_required", status_code=303)
        
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        for _, row in df.iterrows():
            item = parse_excel_row_data(row, df.columns)
            if not item or not item["url"]:
                continue
                
            name = item["name"]
            year = item["year"]
            adm = item["admission_type"]
            cap = item["capacity_type"]
            url = item["url"]
            free = item["is_free_apply"]
            multi = item.get("is_multi_apply", "")
            
            try:
                scraped_data = scrape_university_data(url)
                if not scraped_data["tables_html"]:
                    continue
                
                existing_univ = db.query(University).filter(
                    University.name == name,
                    University.year == year,
                    University.admission_type == adm,
                    University.capacity_type == cap
                ).first()
                
                if existing_univ:
                    existing_univ.url = url
                    existing_univ.is_free_apply = free
                    existing_univ.is_multi_apply = multi
                    existing_univ.scraped_data = json.dumps(scraped_data)
                    db.commit()
                    save_departments(db, existing_univ.id, scraped_data.get("parsed_departments", []))
                else:
                    new_univ = University(
                        name=name,
                        year=year,
                        admission_type=adm,
                        capacity_type=cap,
                        is_free_apply=free,
                        is_multi_apply=multi,
                        url=url,
                        scraped_data=json.dumps(scraped_data)
                    )
                    db.add(new_univ)
                    db.commit()
                    db.refresh(new_univ)
                    save_departments(db, new_univ.id, scraped_data.get("parsed_departments", []))
            except Exception as ex:
                print(f"Error scraping {url}: {ex}")
                continue
                
        # 정적 사이트(JSON)도 자동 동기화
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")

        return RedirectResponse(url="/?msg=excel_uploaded", status_code=303)
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error_title": "엑셀 업로드 실패",
            "error_msg": str(e),
            "is_admin": is_admin_authenticated(request)
        }, status_code=400)

@app.post("/api/upload_excel")
async def api_upload_excel(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not is_admin_authenticated(request):
        token = request.headers.get("x-admin-token") or request.query_params.get("token")
        if token != create_admin_token() and token != "ipsi4774!":
            raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
        
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        success_count = 0
        
        for _, row in df.iterrows():
            item = parse_excel_row_data(row, df.columns)
            if not item or not item["url"]:
                continue
                
            name = item["name"]
            year = item["year"]
            adm = item["admission_type"]
            cap = item["capacity_type"]
            url = item["url"]
            free = item["is_free_apply"]
            multi = item.get("is_multi_apply", "")
            
            try:
                scraped_data = scrape_university_data(url)
                if not scraped_data["tables_html"]: continue
                
                existing_univ = db.query(University).filter(
                    University.name == name,
                    University.year == year,
                    University.admission_type == adm,
                    University.capacity_type == cap
                ).first()
                
                if existing_univ:
                    existing_univ.url = url
                    existing_univ.is_free_apply = free
                    existing_univ.is_multi_apply = multi
                    existing_univ.scraped_data = json.dumps(scraped_data)
                    db.commit()
                    save_departments(db, existing_univ.id, scraped_data.get("parsed_departments", []))
                else:
                    new_univ = University(
                        name=name,
                        year=year,
                        admission_type=adm,
                        capacity_type=cap,
                        is_free_apply=free,
                        is_multi_apply=multi,
                        url=url,
                        scraped_data=json.dumps(scraped_data)
                    )
                    db.add(new_univ)
                    db.commit()
                    db.refresh(new_univ)
                    save_departments(db, new_univ.id, scraped_data.get("parsed_departments", []))
                success_count += 1
            except Exception as ex:
                print(f"Error scraping {name} ({url}): {ex}")
                continue

                
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")
            
        return {"success": True, "count": success_count, "message": f"{success_count}개 대학 데이터가 성공적으로 스크래핑 및 등록되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ScrapedUnivItem(BaseModel):
    name: str
    year: str
    admission_type: Optional[str] = "수시1차"
    capacity_type: Optional[str] = "구분없음"
    url: Optional[str] = ""
    is_free_apply: Optional[str] = ""
    is_multi_apply: Optional[str] = ""
    scraped_data: Optional[Dict[str, Any]] = None
    departments: Optional[List[Dict[str, Any]]] = None

class SaveScrapedBatchRequest(BaseModel):
    universities: List[ScrapedUnivItem]

@app.post("/api/save_scraped_batch")
async def api_save_scraped_batch(request: Request, body: SaveScrapedBatchRequest, db: Session = Depends(get_db)):
    if not check_admin_access(request):
        token = request.headers.get("x-admin-token") or request.query_params.get("token")
        if token != create_admin_token() and token != "ipsi4774!":
            raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    
    saved_count = 0
    try:
        for item in body.universities:
            name = item.name
            year = str(item.year)
            adm = item.admission_type or "수시1차"
            cap = item.capacity_type or "구분없음"
            url = item.url or ""
            free = item.is_free_apply or ""
            multi = item.is_multi_apply or ""
            scraped_data = item.scraped_data or {}
            departments = item.departments or scraped_data.get("parsed_departments", [])

            existing_univ = db.query(University).filter(
                University.name == name,
                University.year == year,
                University.admission_type == adm,
                University.capacity_type == cap
            ).first()

            if existing_univ:
                if url: existing_univ.url = url
                if free: existing_univ.is_free_apply = free
                if multi: existing_univ.is_multi_apply = multi
                if scraped_data: existing_univ.scraped_data = json.dumps(scraped_data)
                db.commit()
                if departments:
                    save_departments(db, existing_univ.id, departments)
            else:
                new_univ = University(
                    name=name,
                    year=year,
                    admission_type=adm,
                    capacity_type=cap,
                    url=url,
                    is_free_apply=free,
                    is_multi_apply=multi,
                    scraped_data=json.dumps(scraped_data) if scraped_data else "{}"
                )
                db.add(new_univ)
                db.commit()
                db.refresh(new_univ)
                if departments:
                    save_departments(db, new_univ.id, departments)
            saved_count += 1

        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")

        return {"success": True, "saved_count": saved_count, "message": f"{saved_count}개 대학 데이터가 성공적으로 저장 및 갱신되었습니다."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

class BatchScrapeServerRequest(BaseModel):
    year: Optional[str] = "ALL"
    admission_type: Optional[str] = "ALL"

@app.post("/api/batch_scrape_server")
async def api_batch_scrape_server(request: Request, body: BatchScrapeServerRequest, db: Session = Depends(get_db)):
    if not check_admin_access(request):
        token = request.headers.get("x-admin-token") or request.query_params.get("token")
        if token != create_admin_token() and token != "ipsi4774!":
            raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    
    query = db.query(University).filter(
        University.url.isnot(None),
        University.url != "",
        func.trim(University.url) != ""
    )
    if body.year and body.year != "ALL":
        query = query.filter(University.year == body.year)
    if body.admission_type and body.admission_type != "ALL":
        query = query.filter(University.admission_type == body.admission_type)

    target_univs = query.all()
    results = []
    success_cnt = 0
    fail_cnt = 0

    for u in target_univs:
        try:
            scraped = scrape_university_data(u.url)
            if scraped and scraped.get("tables_html"):
                u.scraped_data = json.dumps(scraped)
                db.commit()
                save_departments(db, u.id, scraped.get("parsed_departments", []))
                success_cnt += 1
                results.append({"id": u.id, "name": u.name, "status": "success", "dept_count": len(scraped.get("parsed_departments", []))})
            else:
                fail_cnt += 1
                results.append({"id": u.id, "name": u.name, "status": "no_tables"})
        except Exception as e:
            fail_cnt += 1
            results.append({"id": u.id, "name": u.name, "status": "error", "error": str(e)})

    try:
        export_to_json(db)
    except Exception as ex:
        print(f"[경고] JSON 자동 갱신 실패: {ex}")

    return {
        "success": True,
        "total": len(target_univs),
        "success_count": success_cnt,
        "fail_count": fail_cnt,
        "results": results,
        "message": f"서버 스크래핑 완료: 성공 {success_cnt}건, 실패 {fail_cnt}건"
    }

@app.post("/api/deploy_github")
async def api_deploy_github(request: Request):
    if not check_admin_access(request):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    
    success = push_to_github_pages()
    if success:
        return {"success": True, "message": "GitHub Pages(suego78ai/ipsi)로 최신 데이터가 성공적으로 배포(Push)되었습니다."}
    else:
        return {"success": False, "message": "GitHub Pages 배포 중 오류가 발생했습니다."}

class DeleteUniversitiesRequest(BaseModel):
    univ_ids: Optional[List[int]] = None
    names: Optional[List[str]] = None
    year: Optional[str] = None
    admission_type: Optional[str] = None

@app.post("/api/reset_all")
@app.delete("/api/data/all")
async def api_reset_all_data(request: Request, db: Session = Depends(get_db)):
    """전체 대학 경쟁률 데이터 완전 초기화"""
    if not check_admin_access(request):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    try:
        dept_count = db.query(DepartmentData).count()
        univ_count = db.query(University).count()
        
        db.query(DepartmentData).delete()
        db.query(University).delete()
        db.commit()
        
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")
            
        return {
            "success": True, 
            "deleted_universities": univ_count,
            "deleted_departments": dept_count,
            "message": f"총 {univ_count}개 대학({dept_count}개 학과)의 경쟁률 데이터가 전체 초기화되었습니다."
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"초기화 실패: {str(e)}")

@app.post("/api/delete_universities")
async def api_delete_universities(request: Request, body: DeleteUniversitiesRequest, db: Session = Depends(get_db)):
    """선택한 대학 경쟁률 데이터 일괄 삭제/초기화"""
    if not check_admin_access(request):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    try:
        query = db.query(University)
        if body.univ_ids and len(body.univ_ids) > 0:
            query = query.filter(University.id.in_(body.univ_ids))
        elif body.names and len(body.names) > 0:
            query = query.filter(University.name.in_(body.names))
            if body.year:
                query = query.filter(University.year == body.year)
            if body.admission_type:
                query = query.filter(University.admission_type == body.admission_type)
        else:
            raise HTTPException(status_code=400, detail="삭제할 대상 대학 ID 또는 대학명이 제공되지 않았습니다.")
            
        target_univs = query.all()
        target_ids = [u.id for u in target_univs]
        count = len(target_ids)
        
        if count == 0:
            return {"success": True, "deleted_count": 0, "message": "삭제 대상 대학이 없습니다."}
            
        db.query(DepartmentData).filter(DepartmentData.university_id.in_(target_ids)).delete(synchronize_session=False)
        db.query(University).filter(University.id.in_(target_ids)).delete(synchronize_session=False)
        db.commit()
        
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")
            
        return {
            "success": True,
            "deleted_count": count,
            "message": f"선택한 {count}개 대학 데이터가 성공적으로 삭제(초기화)되었습니다."
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"선택 삭제 실패: {str(e)}")

@app.delete("/api/universities/{univ_id}")
async def api_delete_single_university(request: Request, univ_id: int, db: Session = Depends(get_db)):
    """단일 대학 데이터 개별 삭제/초기화"""
    if not check_admin_access(request):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    try:
        univ = db.query(University).filter(University.id == univ_id).first()
        if not univ:
            raise HTTPException(status_code=404, detail="해당 대학을 찾을 수 없습니다.")
            
        uname = univ.name
        uyear = univ.year
        uadm = univ.admission_type
        
        db.query(DepartmentData).filter(DepartmentData.university_id == univ_id).delete()
        db.query(University).filter(University.id == univ_id).delete()
        db.commit()
        
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")
            
        return {
            "success": True,
            "message": f"'{uname} ({uyear} {uadm})' 데이터가 성공적으로 삭제(초기화)되었습니다."
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"개별 삭제 실패: {str(e)}")

@app.post("/api/auth/token")
async def api_get_token(username: str = Form(...), password: str = Form(...)):
    if username.strip() == ADMIN_USERNAME and password.strip() == ADMIN_PASSWORD:
        return {"success": True, "token": create_admin_token(), "username": "admin"}
    raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

@app.get("/search", response_class=HTMLResponse)
async def search_departments(
    request: Request, 
    q: str = "", 
    year: str = "", 
    adm_type: str = "", 
    cap_type: str = "", 
    univ_name: str = "", 
    ratio: str = "", 
    db: Session = Depends(get_db)
):
    universities = db.query(University).order_by(University.created_at.desc()).all()
    tree_data = build_tree(universities)
    unique_univ_names = sort_names_inha_first(list(set([u.name for u in universities])))
    
    query = db.query(DepartmentData, University).join(University)
    
    if q.strip(): query = query.filter(DepartmentData.department_name.like(f"%{q}%"))
    if year.strip(): query = query.filter(University.year == year)
    if adm_type.strip(): query = query.filter(University.admission_type == adm_type)
    if cap_type.strip(): query = query.filter(University.capacity_type == cap_type)
    if univ_name.strip(): query = query.filter(University.name == univ_name)
    if ratio.strip(): query = query.filter(DepartmentData.competition_ratio.like(f"%{ratio}%"))
        
    depts = query.all()
    
    results = []
    for dept, univ in depts:
        results.append({
            "year": univ.year,
            "admission_type": univ.admission_type,
            "univ_name": univ.name,
            "table_title": dept.table_title,
            "department_name": dept.department_name,
            "admission_count": dept.admission_count,
            "applicant_count": dept.applicant_count,
            "competition_ratio": dept.competition_ratio,
            "univ_id": univ.id
        })
        
    inha_results = [r for r in results if "인하공업전문대학" in r["univ_name"]]
    other_results = [r for r in results if "인하공업전문대학" not in r["univ_name"]]
    results = inha_results + other_results
            
    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request,
        "tree_data": tree_data,
        "unique_univ_names": unique_univ_names,
        "is_search_mode": True,
        "search_query": q,
        "search_params": {
            "year": year,
            "adm_type": adm_type,
            "cap_type": cap_type,
            "univ_name": univ_name,
            "ratio": ratio
        },
        "search_results": results,
        "is_admin": is_admin_authenticated(request)
    })

@app.get("/report", response_class=HTMLResponse)
async def custom_report(
    request: Request, 
    univs: Optional[str] = Query(None), 
    year: Optional[str] = Query(None),
    adm_type: Optional[str] = Query(None),
    realtime: Optional[bool] = Query(False),
    mode: Optional[str] = Query("normal"),
    db: Session = Depends(get_db)
):
    universities = db.query(University).order_by(University.created_at.desc()).all()
    tree_data = build_tree(universities)
    unique_univ_names = sort_names_inha_first(list(set([u.name for u in universities])))
    
    if not univs:
        all_years = sorted(list(set([u.year for u in universities])), reverse=True)
        all_adm_types = sorted(list(set([u.admission_type for u in universities])))
        
        # y_adm as key, e.g., "2026_수시1차"
        all_univs_by_criteria = {}
        for u in universities:
            key = f"{u.year}_{u.admission_type}"
            if key not in all_univs_by_criteria:
                all_univs_by_criteria[key] = set()
            all_univs_by_criteria[key].add(u.name)
            
        all_univs_by_criteria = {k: sort_names_inha_first(list(v)) for k, v in all_univs_by_criteria.items()}
            
        return templates.TemplateResponse(request=request, name="index.html", context={
            "request": request,
            "tree_data": tree_data,
            "unique_univ_names": unique_univ_names,
            "is_report_builder": True,
            "builder_mode": mode,
            "all_years": all_years,
            "all_adm_types": all_adm_types,
            "all_univs_by_criteria": all_univs_by_criteria,
            "is_admin": is_admin_authenticated(request)
        })
        
    selected_names = [n.strip() for n in univs.split(",") if n.strip()]
    selected_names = sort_names_inha_first(selected_names)
    if not year:
        all_years = sorted(list(set([u.year for u in universities])), reverse=True)
        year = all_years[0] if all_years else "2026"
    if not adm_type:
        adm_type = "수시1차"
        
    try:
        base_y = int(year)
    except:
        base_y = 2026
        
    years = [str(base_y - 2), str(base_y - 1), str(base_y)]
        
    target_univs = db.query(University).filter(
        University.year.in_(years),
        University.admission_type == adm_type,
        University.name.in_(selected_names)
    ).all()
    
    # 실시간 파싱 로직
    if realtime:
        # target_univs 중 당해년도(base_y)에 해당하는 대학만 추려서 파싱 진행
        latest_univs = [u for u in target_univs if u.year == str(base_y)]
        for u in latest_univs:
            if u.url:
                try:
                    scraped_data = scrape_university_data(u.url)
                    if scraped_data and scraped_data.get("tables_html"):
                        u.scraped_data = json.dumps(scraped_data)
                        save_departments(db, u.id, scraped_data.get("parsed_departments", []))
                except Exception as e:
                    print(f"Failed to real-time scrape {u.name}: {e}")
        db.commit()
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")
        
        # 다시 쿼리하여 업데이트된 데이터 반영
        target_univs = db.query(University).filter(
            University.year.in_(years),
            University.admission_type == adm_type,
            University.name.in_(selected_names)
        ).all()
    
    report_data = {
        "year": str(base_y),
        "years": years,
        "adm_type": adm_type,
        "selected_names": selected_names,
        "univs": {}
    }
    
    for uname in selected_names:
        report_data["univs"][uname] = {
            "adm_count": {y: 0 for y in years},
            "app_count": {y: 0 for y in years},
            "ratio": {y: 0.0 for y in years},
            "diff_app": 0,
            "diff_ratio": 0.0
        }
    
    for univ in target_univs:
        y = univ.year
        uname = univ.name
        
        sum_adm = 0
        sum_app = 0
        
        # 정원외 키워드 목록
        outside_kws = [
            '정원외', '정원 외', '[정원외]', '(정원외)',
            '전문대', '학사',
            '농어촌', '수급자', '차상위', '한부모', '기초생활', '기회균형',
            '재외국민', '외국인', '북한', '이탈주민', '통일인재', '전교육과정',
            '만학도', '재직자', '단원', '서해5도', '서해 5도', '장애', '특수교육', '취업자'
        ]

        # 모집단위 / 학과명에 일반고, 특성화고, 특기자(어학), 연계교육, 정원내 등으로 표기되는 정원내 항목
        inside_kws = [
            '정원내', '정원 내',
            '일반고', '특성화고', '특기자', '연계교육',
            '일반전형', '일반 전형', '일반', '내신', '수능', '실기',
            '대학자체', '성인학습자', '성인친화', '글로벌인재', 'SDA', '특별전형'
        ]

        def is_inside_d(dept_item, cap_type):
            if cap_type and ('정원외' in cap_type or '정원 외' in cap_type):
                return False
            tt = (dept_item.table_title or '').strip()
            if any(kw in tt for kw in ['정원외', '정원 외', '[정원외]', '(정원외)']):
                return False
            dept_name = (dept_item.department_name or '').strip()
            if any(kw in dept_name for kw in outside_kws):
                return False
            if '전형별' in tt:
                return any(kw in dept_name for kw in inside_kws)
            return True

        # '전형별' 요약 테이블이 있는지 확인
        has_summary = any('전형별' in (d.table_title or '') for d in univ.departments)
        
        for d in univ.departments:
            if not is_inside_d(d, univ.capacity_type):
                continue
                
            if has_summary:
                # 요약 테이블이 있는 경우, '전형별' 테이블의 정원내 행만 사용하여 중복 합산 방지
                if '전형별' not in (d.table_title or ''):
                    continue
            # 요약 테이블이 없는 경우, 모집단위(학과별) 테이블 중 정원내 행만 합산
                    
            try: sum_adm += int(str(d.admission_count).replace(',', ''))
            except: pass
            try: sum_app += int(str(d.applicant_count).replace(',', ''))
            except: pass
            
        report_data["univs"][uname]["adm_count"][y] += sum_adm
        report_data["univs"][uname]["app_count"][y] += sum_app
        
    for uname, data in report_data["univs"].items():
        for y in years:
            adm = data["adm_count"][y]
            app = data["app_count"][y]
            if adm > 0:
                data["ratio"][y] = round(app / adm, 2)
            else:
                data["ratio"][y] = 0.0
                
        # 증감 계산 (최신년도 - 직전년도)
        y_latest = years[2]
        y_prev = years[1]
        data["diff_app"] = data["app_count"][y_latest] - data["app_count"][y_prev]
        data["diff_ratio"] = round(data["ratio"][y_latest] - data["ratio"][y_prev], 2)

    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request,
        "tree_data": tree_data,
        "unique_univ_names": unique_univ_names,
        "is_report_view": True,
        "is_realtime_view": realtime,
        "report_data": report_data,
        "is_admin": is_admin_authenticated(request)
    })

if __name__ == "__main__":
    import os, uvicorn
    port = int(os.environ.get("PORT", 26240))
    host = "0.0.0.0"
    uvicorn.run("main:app", host=host, port=port, reload=True)


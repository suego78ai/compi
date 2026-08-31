from fastapi import FastAPI, Request, Form, Depends, HTTPException, File, UploadFile, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import json
import pandas as pd
import io
from typing import Optional
from database import SessionLocal, engine, Base, University, DepartmentData
from scraper_service import scrape_university_data
from export_data import export_to_json

import hmac
import hashlib

app = FastAPI()

# Mount templates
templates = Jinja2Templates(directory="templates")

# Admin Authentication
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ipsi4774!"
AUTH_SECRET = "ipsi_admin_auth_secret_token_2027"

def create_admin_token() -> str:
    return hmac.new(AUTH_SECRET.encode(), ADMIN_USERNAME.encode(), hashlib.sha256).hexdigest()

def is_admin_authenticated(request: Request) -> bool:
    token = request.cookies.get("ipsi_admin_token")
    if not token:
        return False
    return hmac.compare_digest(token, create_admin_token())

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

    # Sort keys for consistent UI
    sorted_tree = {k: tree[k] for k in sorted(tree.keys(), reverse=True)}
    return sorted_tree


def calculate_dashboard_insights(db: Session):
    insights = {
        "top_ratio": None,
        "ratio_increase": None,
        "applicant_increase": None,
        "latest_year": None
    }
    
    all_years = [u.year for u in db.query(University.year).distinct().all()]
    if not all_years:
        return insights
        
    try:
        sorted_years = sorted(all_years, key=lambda x: int(x), reverse=True)
        latest_year = sorted_years[0]
        prev_year = sorted_years[1] if len(sorted_years) > 1 else None
    except ValueError:
        return insights
        
    insights["latest_year"] = latest_year
    latest_univs = db.query(University).filter(University.year == latest_year).all()
    if not latest_univs: return insights
        
    max_ratio_val = -1
    max_ratio_univ = ""
    univ_stats = {}
    
    for univ in latest_univs:
        if univ.name not in univ_stats:
            univ_stats[univ.name] = {"latest_max_ratio": 0, "prev_max_ratio": 0, "latest_total_app": 0, "prev_total_app": 0}
            
        for dept in univ.departments:
            try:
                r_val = float(dept.competition_ratio.split(':')[0].strip())
            except Exception:
                r_val = 0
                
            if r_val > univ_stats[univ.name]["latest_max_ratio"]:
                univ_stats[univ.name]["latest_max_ratio"] = r_val
            if r_val > max_ratio_val:
                max_ratio_val = r_val
                max_ratio_univ = univ.name
                
            try:
                app_val = int(str(dept.applicant_count).replace(',', '').strip())
            except Exception:
                app_val = 0
            univ_stats[univ.name]["latest_total_app"] += app_val
            
    if max_ratio_val > 0:
        insights["top_ratio"] = {
            "univ_name": max_ratio_univ,
            "value": f"{max_ratio_val:.2f}:1"
        }
        
    if prev_year:
        prev_univs = db.query(University).filter(University.year == prev_year).all()
        for univ in prev_univs:
            if univ.name not in univ_stats: continue
            for dept in univ.departments:
                try:
                    r_val = float(dept.competition_ratio.split(':')[0].strip())
                except Exception:
                    r_val = 0
                if r_val > univ_stats[univ.name]["prev_max_ratio"]:
                    univ_stats[univ.name]["prev_max_ratio"] = r_val
                try:
                    app_val = int(str(dept.applicant_count).replace(',', '').strip())
                except Exception:
                    app_val = 0
                univ_stats[univ.name]["prev_total_app"] += app_val
                
        max_ratio_inc = -9999
        max_ratio_inc_univ = ""
        max_app_inc = -999999
        max_app_inc_univ = ""
        
        for u_name, stats in univ_stats.items():
            if stats["prev_max_ratio"] > 0:
                inc = stats["latest_max_ratio"] - stats["prev_max_ratio"]
                if inc > max_ratio_inc:
                    max_ratio_inc = inc
                    max_ratio_inc_univ = u_name
            if stats["prev_total_app"] > 0:
                inc = stats["latest_total_app"] - stats["prev_total_app"]
                if inc > max_app_inc:
                    max_app_inc = inc
                    max_app_inc_univ = u_name
                    
        if max_ratio_inc_univ:
            insights["ratio_increase"] = {
                "univ_name": max_ratio_inc_univ,
                "value": f"+{max_ratio_inc:.2f}p 상승" if max_ratio_inc > 0 else f"{max_ratio_inc:.2f}p"
            }
        if max_app_inc_univ:
            insights["applicant_increase"] = {
                "univ_name": max_app_inc_univ,
                "value": f"+{max_app_inc:,}명 증가" if max_app_inc > 0 else f"{max_app_inc:,}명"
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
            "URL": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio41260471.html",
            "정원구분": "정원내"
        },
        {
            "학년도": "2027",
            "모집시기": "수시1차",
            "대학명": "유한대학교",
            "URL": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio41280381.html",
            "정원구분": "구분없음"
        },
        {
            "학년도": "2027",
            "모집시기": "수시2차",
            "대학명": "동양미래대학교",
            "URL": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio41150241.html",
            "정원구분": "구분없음"
        }
    ]
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="경쟁률_등록서식")
        
        # openpyxl 스타일 및 컬럼 너비 자동 조정
        ws = writer.sheets["경쟁률_등록서식"]
        col_widths = {"A": 12, "B": 14, "C": 22, "D": 65, "E": 14}
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="ipsi_template.xlsx"'
    }
    return StreamingResponse(output, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.post("/upload_excel")
async def upload_excel(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not is_admin_authenticated(request):
        return RedirectResponse(url="/login?error=auth_required", status_code=303)
        
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # D열을 URL로 인식하도록 컬럼 인덱스로 접근 (0=A, 1=B, 2=C, 3=D, 4=E)
        for _, row in df.iterrows():
            if len(row) < 4:
                continue # 최소 D열(URL)까지는 있어야 함
                
            url_val = row.iloc[3]
            if pd.isna(url_val) or not str(url_val).strip():
                continue

            year = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
            adm = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else ""
            name = str(row.iloc[2]).strip() if not pd.isna(row.iloc[2]) else ""
            url = str(url_val).strip()
            
            # E열(정원)이 존재하면 가져오고 없으면 '구분없음'
            cap = str(row.iloc[4]).strip() if len(row) > 4 and not pd.isna(row.iloc[4]) else "구분없음"
            
            try:
                scraped_data = scrape_university_data(url)
                if not scraped_data["tables_html"]:
                    continue # Skip if no tables
                
                existing_univ = db.query(University).filter(
                    University.name == name,
                    University.year == year,
                    University.admission_type == adm,
                    University.capacity_type == cap
                ).first()
                
                if existing_univ:
                    existing_univ.url = url
                    existing_univ.scraped_data = json.dumps(scraped_data)
                    db.commit()
                    save_departments(db, existing_univ.id, scraped_data.get("parsed_departments", []))
                else:
                    new_univ = University(
                        name=name,
                        year=year,
                        admission_type=adm,
                        capacity_type=cap,
                        url=url,
                        scraped_data=json.dumps(scraped_data)
                    )
                    db.add(new_univ)
                    db.commit()
                    db.refresh(new_univ)
                    save_departments(db, new_univ.id, scraped_data.get("parsed_departments", []))
            except Exception as e:
                print(f"Error scraping {url}: {e}")
                continue
                
        # 정적 사이트(JSON)도 자동 동기화
        try:
            export_to_json(db)
        except Exception as ex:
            print(f"[경고] JSON 자동 갱신 실패: {ex}")

        return RedirectResponse(url="/", status_code=303)
    except Exception as e:
        all_univs = db.query(University).order_by(University.created_at.desc()).all()
        unique_univ_names = sorted(list(set([u.name for u in all_univs])))
        return templates.TemplateResponse(request=request, name="index.html", context={
            "tree_data": build_tree(all_univs),
            "unique_univ_names": unique_univ_names,
            "error_msg": f"엑셀 업로드 오류: {str(e)}"
        }, status_code=400)

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
        
        # '전형별' 요약 테이블이 있는지 확인
        has_summary = any('전형별' in d.table_title for d in univ.departments)
        
        for d in univ.departments:
            # 정원외 키워드
            outside_kws = ['농어촌', '수급자', '차상위', '전문대졸', '학사', '북한', '재외국민', '외국인', '만학도', '단원', '취업자', '장애']
            
            if has_summary:
                # 요약 테이블이 있는 경우, '전형별' 테이블의 행만 사용하여 중복 방지
                if '전형별' not in d.table_title:
                    continue
                # 정원외 전형은 제외하여 '정원내 소계'와 동일하게 맞춤
                if any(kw in d.department_name for kw in outside_kws):
                    continue
            else:
                # 요약 테이블이 없는 경우, 일반 학과 테이블들을 합산 (정원외 제외)
                if any(kw in d.table_title or kw in d.department_name for kw in outside_kws):
                    continue
                    
            try: sum_adm += int(d.admission_count.replace(',', ''))
            except: pass
            try: sum_app += int(d.applicant_count.replace(',', ''))
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


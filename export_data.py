"""
export_data.py
--------------
ipsi.db 데이터를 data/data.json 으로 export 합니다.
GitHub Pages 정적 대시보드용 데이터 파일을 생성합니다.

사용법:
    python export_data.py
"""

import json
import os
import sys
from pathlib import Path

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base, University, DepartmentData
except ImportError as e:
    print(f"[오류] 패키지가 없습니다: {e}")
    print("      pip install -r requirements.txt 를 먼저 실행하세요.")
    sys.exit(1)

DB_PATH = Path(__file__).parent / "ipsi.db"
OUT_DIR  = Path(__file__).parent / "data"
OUT_FILE = OUT_DIR / "data.json"

def export_to_json(db=None):
    close_db = False
    if db is None:
        if not DB_PATH.exists():
            print(f"[오류] DB 파일을 찾을 수 없습니다: {DB_PATH}")
            return False
        engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine)
        db = Session()
        close_db = True

    try:
        universities = db.query(University).order_by(University.year.desc(), University.name).all()

        records = []
        for u in universities:
            departments = []
            for d in u.departments:
                departments.append({
                    "table_title":       d.table_title or "",
                    "department_name":   d.department_name or "",
                    "admission_count":   d.admission_count or "",
                    "applicant_count":   d.applicant_count or "",
                    "competition_ratio": d.competition_ratio or "",
                })

            scraped = {}
            try:
                if u.scraped_data:
                    scraped = json.loads(u.scraped_data)
            except Exception:
                pass

            records.append({
                "id":             u.id,
                "name":           u.name or "",
                "year":           u.year or "",
                "admission_type": u.admission_type or "",
                "capacity_type":  u.capacity_type or "",
                "url":            u.url or "",
                "departments":    departments,
                "scraped_data":   scraped,
            })

        OUT_DIR.mkdir(exist_ok=True)
        payload = {
            "universities": records,
            "exported_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        }
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        size_kb = OUT_FILE.stat().st_size / 1024
        print(f"[성공] JSON export 완료: {OUT_FILE} ({len(records)}개 대학, {size_kb:.1f} KB)")
        return True
    finally:
        if close_db:
            db.close()

def main():
    print("[1/2] DB 데이터 읽는 중...")
    export_to_json()
    print("[2/2] 완료되었습니다.")

if __name__ == "__main__":
    main()

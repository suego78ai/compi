import json
import os
import sys
import subprocess
import shutil
from pathlib import Path

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base, University, DepartmentData
except ImportError as e:
    print(f"[오류] 패키지가 없습니다: {e}")
    print("      pip install -r requirements.txt 를 먼저 실행하세요.")
    sys.exit(1)

ROOT_DIR = Path(__file__).parent
DB_PATH = ROOT_DIR / "ipsi.db"
OUT_DIR  = ROOT_DIR / "data"
OUT_FILE = OUT_DIR / "data.json"
IPSI_REPO_DIR = ROOT_DIR / "ipsi_repo"

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

        TABLE_PRIORITY = [
            '전형별 경쟁률 현황',
            '일반전형 경쟁률 현황',
            '일반고 경쟁률 현황',
            '일반고전형 경쟁률 현황',
            '일반고 전형 경쟁률 현황',
        ]
        def p_score(t):
            for i, p in enumerate(TABLE_PRIORITY):
                if p == (t or ''): return i
            return len(TABLE_PRIORITY)

        records = []
        for u in universities:
            depts = u.departments
            is_free = getattr(u, 'is_free_apply', '') or ('F' if str(u.name or '').endswith(('F', '(F)')) else '')
            if is_free == 'M': is_free = 'F'
            is_multi = getattr(u, 'is_multi_apply', '') or ('M' if str(u.name or '').endswith(('M', '(M)')) else '')
            if not depts:
                records.append({
                    "id": u.id, "name": u.name or "", "year": str(u.year or ""),
                    "adm_type": u.admission_type or "수시1차", "admission_type": u.admission_type or "수시1차",
                    "cap_type": u.capacity_type or "구분없음", "capacity_type": u.capacity_type or "구분없음",
                    "free_apply": is_free, "is_free_apply": is_free, "무료접수": is_free,
                    "multi_apply": is_multi, "is_multi_apply": is_multi, "중복지원": is_multi,
                    "url": u.url or "", "dept": "", "department_name": "", "table_title": "",
                    "recruit_num": "", "admission_count": "", "applicant_num": "", "applicant_count": "",
                    "competition_rate": "", "competition_ratio": ""
                })
                continue

            dept_map = {}
            for d in depts:
                key = (d.department_name or '').strip()
                score = p_score(d.table_title)
                existing = dept_map.get(key)
                if existing is None or score < existing[0]:
                    dept_map[key] = (score, d)

            for dept_name, (_, d) in dept_map.items():
                records.append({
                    "id": u.id, "name": u.name or "", "year": str(u.year or ""),
                    "adm_type": u.admission_type or "수시1차", "admission_type": u.admission_type or "수시1차",
                    "cap_type": u.capacity_type or "구분없음", "capacity_type": u.capacity_type or "구분없음",
                    "free_apply": is_free, "is_free_apply": is_free, "무료접수": is_free,
                    "multi_apply": is_multi, "is_multi_apply": is_multi, "중복지원": is_multi,
                    "url": u.url or "", "dept": d.department_name or "", "department_name": d.department_name or "",
                    "table_title": d.table_title or "",
                    "recruit_num": d.admission_count or "", "admission_count": d.admission_count or "",
                    "applicant_num": d.applicant_count or "", "applicant_count": d.applicant_count or "",
                    "competition_rate": d.competition_ratio or "", "competition_ratio": d.competition_ratio or ""
                })

        OUT_DIR.mkdir(exist_ok=True)
        payload = {
            "universities": records,
            "total": len(records),
            "exported_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        }
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        size_kb = OUT_FILE.stat().st_size / 1024
        print(f"[성공] JSON export 완료: {OUT_FILE} ({len(records)}개 대학, {size_kb:.1f} KB)")

        # Sync to ipsi_repo if exists
        if IPSI_REPO_DIR.exists() and (IPSI_REPO_DIR / ".git").exists():
            target_data_dir = IPSI_REPO_DIR / "data"
            target_data_dir.mkdir(exist_ok=True)
            shutil.copy2(OUT_FILE, target_data_dir / "data.json")
            if (ROOT_DIR / "index.html").exists():
                shutil.copy2(ROOT_DIR / "index.html", IPSI_REPO_DIR / "index.html")
            if (ROOT_DIR / "xlsx.full.min.js").exists():
                shutil.copy2(ROOT_DIR / "xlsx.full.min.js", IPSI_REPO_DIR / "xlsx.full.min.js")
            print(f"[동기화] ipsi_repo 저장소로 최신 파일 동기화 완료.")

        return True
    finally:
        if close_db:
            db.close()

def push_to_github_pages(commit_msg="Update latest ipsi data (data.json)"):
    export_to_json()
    if not (IPSI_REPO_DIR.exists() and (IPSI_REPO_DIR / ".git").exists()):
        print(f"[경고] ipsi_repo 폴더를 찾을 수 없습니다: {IPSI_REPO_DIR}")
        return False

    try:
        subprocess.run(["git", "add", "data/data.json", "index.html", "xlsx.full.min.js"], cwd=IPSI_REPO_DIR, check=True)
        # Check if there are changes to commit
        status = subprocess.run(["git", "status", "--porcelain"], cwd=IPSI_REPO_DIR, capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=IPSI_REPO_DIR, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=IPSI_REPO_DIR, check=True)
            print("[배포 성공] GitHub Pages(suego78ai/ipsi)로 푸시 완료! 약 1분 후 반영됩니다.")
        else:
            print("[배포] 변경된 데이터가 없어 푸시를 건너뜁니다.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[오류] Git 배포 중 에러 발생: {e}")
        return False

def main():
    print("[1/2] DB 데이터 읽는 중...")
    if "--push" in sys.argv or "-p" in sys.argv:
        push_to_github_pages()
    else:
        export_to_json()
    print("[2/2] 완료되었습니다.")

if __name__ == "__main__":
    main()

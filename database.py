from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime

import os
from pathlib import Path

# DB 파일의 절대 경로 지정 (실행 위치에 관계없이 항상 프로젝트의 ipsi.db 참조)
DB_FILE = Path(__file__).resolve().parent / "ipsi.db"
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_FILE}")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class University(Base):
    __tablename__ = "universities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    year = Column(String)            # 2024, 2025 등
    admission_type = Column(String)  # 수시1차, 수시2차, 정시
    capacity_type = Column(String)   # 정원내, 정원외, 구분없음
    url = Column(String)
    scraped_data = Column(Text) # Stores JSON: {"titles": [...], "tables_html": [...]}
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    departments = relationship("DepartmentData", back_populates="university", cascade="all, delete-orphan")

class DepartmentData(Base):
    __tablename__ = "department_data"
    
    id = Column(Integer, primary_key=True, index=True)
    university_id = Column(Integer, ForeignKey("universities.id"))
    table_title = Column(String)
    department_name = Column(String, index=True)
    admission_count = Column(String)
    applicant_count = Column(String)
    competition_ratio = Column(String)
    
    university = relationship("University", back_populates="departments")

Base.metadata.create_all(bind=engine)

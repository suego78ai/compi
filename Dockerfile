FROM python:3.12-alpine

# 환경 변수 설정
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=26240

WORKDIR /app

# 시스템 의존성 설치 (컴파일 및 C 라이브러리 지원)
RUN apk update && apk upgrade && apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev

# 파이썬 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 및 기본 DB/데이터 복사
COPY . .

# 포트 노출
EXPOSE 26240

# 서버 실행 (환경변수 PORT 지원)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-26240}"]


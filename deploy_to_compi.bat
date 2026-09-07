@echo off
chcp 65001 > nul
echo ========================================================
echo   [입시 대시보드] https://compi.mojuk.kr 전용 자동 배포
echo ========================================================
echo.
echo [1/2] 로컬 DB 데이터를 data.json 으로 변환 및 compi.mojuk.kr 배포 준비 중...
python export_data.py --push
echo.
echo [2/2] https://compi.mojuk.kr 배포 처리가 완료되었습니다.
echo.
echo 메인 서버 (https://compi.mojuk.kr/) 에 최신 데이터가 반영됩니다.
echo ========================================================
pause

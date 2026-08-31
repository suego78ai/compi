@echo off
chcp 65001 > nul
echo ========================================================
echo   [입시 대시보드] GitHub Pages 자동 배포 (data.json)
echo ========================================================
echo.
echo [1/2] 로컬 DB 데이터를 data.json 으로 변환 및 동기화 중...
python export_data.py --push
echo.
echo [2/2] 배포 처리가 완료되었습니다.
echo.
echo GitHub Pages (https://suego78ai.github.io/ipsi/) 에 약 1분 후 반영됩니다.
echo ========================================================
pause

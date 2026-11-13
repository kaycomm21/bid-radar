@echo off
chcp 65001 > nul
echo ============================================================
echo   🎯 BID RADAR (비드레이더) 데이터 갱신 ^& GitHub 자동 배포
echo ============================================================
cd /d "%~dp0"
python "ⓐ_261113_export_data.py" --deploy
if errorlevel 1 (
    echo [오류] 실행 중 문제가 발생했습니다. 로그를 확인하세요.
    pause
    exit /b 1
)
echo.
echo ✅ 완료! 약 1~2분 뒤 아래 주소에 최신 데이터가 반영됩니다:
echo    https://kaycomm21.github.io/bid-radar/
pause

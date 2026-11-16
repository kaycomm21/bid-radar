@echo off
chcp 65001 > nul
rem BID RADAR 순위·점수 매일 이어받기 (나라장터 순위 API 는 하루 1,000건 한도)
rem  1) 남은 공고의 순위를 한도까지 수집  2) ranks.js 만 커밋·푸시  (노션은 건드리지 않음)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo ==== %date% %time% ==== >> ranks_daily.log
python "ⓒ_261117_fetch_ranks.py" 990 >> ranks_daily.log 2>&1
python -c "import sys,importlib; sys.path.insert(0,'.'); importlib.import_module('ⓐ_261113_export_data').verify_no_secrets()" >> ranks_daily.log 2>&1
if errorlevel 1 (
    echo [중단] 시크릿 검사 실패 >> ranks_daily.log
    exit /b 1
)
git add ranks.js >> ranks_daily.log 2>&1
git diff --cached --quiet
if errorlevel 1 (
    git commit -q -m "chore: daily rank data update" >> ranks_daily.log 2>&1
    git push origin main >> ranks_daily.log 2>&1
)
exit /b 0

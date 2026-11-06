@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 중고차 추천 앱을 시작합니다... (창을 닫으면 앱이 종료됩니다)
python -m pip install -q -r requirements.txt
python -m streamlit run ui/app.py --server.port 8501
pause

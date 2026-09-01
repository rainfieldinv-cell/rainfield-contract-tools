@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo.
echo  레인필드 계약서 도구 - 웹 화면을 띄웁니다.
echo  (창을 닫으면 종료됩니다)
echo.
python -m streamlit run app.py
pause

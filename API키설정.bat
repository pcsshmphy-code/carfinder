@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo  Claude AI 코멘트용 API 키 설정
echo  (키는 이 PC의 .env 파일에만 저장되며 GitHub에 올라가지 않습니다)
echo ==================================================
echo.
echo  1) https://console.anthropic.com  ^>  API Keys 에서 키 복사
echo  2) 아래에 붙여넣기(마우스 오른쪽 클릭) 후 Enter
echo.
set /p KEY=API 키 (sk-ant-...):
if "%KEY%"=="" (
  echo 입력이 없어 취소했습니다.
  pause
  exit /b 1
)
echo %KEY%| findstr /b "sk-ant-" >nul
if errorlevel 1 (
  echo [경고] 키가 sk-ant- 로 시작하지 않습니다. 다시 확인하세요.
  pause
  exit /b 1
)
> .env echo ANTHROPIC_API_KEY=%KEY%
echo.
echo 저장 완료: %CD%\.env
echo 앱 창을 닫고 '앱실행.bat'을 다시 실행하면 AI 코멘트가 나옵니다.
pause

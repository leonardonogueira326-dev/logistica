@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Rode instalar.bat primeiro.
  pause
  exit /b 1
)

rem IA local: troque o modelo aqui se quiser testar outro (ex.: qwen2.5:7b)
set LOGISTICA_OLLAMA_MODEL=qwen2.5:3b
if not exist logs mkdir logs

rem Se uma versao antiga ainda estiver rodando, fecha antes (senao a nova nao entra)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
echo Preparando as telas (leva alguns segundos)...
if exist route-genius-main\dist rmdir /s /q route-genius-main\dist
pushd route-genius-main
call npm run build > ..\logs\build.log 2>&1
popd
if not exist route-genius-main\dist\client\_shell.html goto modo_alternativo

echo.
echo Sistema em http://localhost:8000  - feche esta janela para desligar.
start "" http://localhost:8000
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
goto fim

:modo_alternativo
echo.
echo [AVISO] Nao consegui compilar as telas. Detalhes em logs\build.log
echo         Abrindo no modo alternativo - duas janelas, nao feche nenhuma.
start "Logistica - Tela - nao feche" cmd /k "cd /d %~dp0route-genius-main && npm run dev -- --port 5173 --host 127.0.0.1 > ..\logs\tela.log 2>&1"
start "" cmd /c "timeout /t 10 /nobreak >nul & start http://localhost:5173"
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000

:fim
pause

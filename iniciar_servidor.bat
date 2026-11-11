@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Modo servidor: outros PCs da rede da empresa acessam pelo navegador.
if not exist .venv\Scripts\python.exe (
  echo Rode instalar.bat primeiro.
  pause & exit /b 1
)
set LOGISTICA_OLLAMA_MODEL=qwen2.5:3b

where git >nul 2>&1 && git pull -q --ff-only >nul 2>&1
call scripts\sincronizar_dados.bat
if not exist logs mkdir logs
rem Se uma versao antiga ainda estiver rodando, fecha antes (senao a nova nao entra)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
echo Preparando as telas...
if exist route-genius-main\dist rmdir /s /q route-genius-main\dist
pushd route-genius-main
call npm run build > ..\logs\build.log 2>&1
popd
if not exist route-genius-main\dist\client\_shell.html (
  echo [ERRO] Falha ao compilar as telas. Detalhes em logs\build.log
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Sistema de logistica no ar. Nos outros PCs, abra no navegador:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo     http://%%a:8000
echo  Se o Windows perguntar sobre o Firewall, clique em "Permitir".
echo  Nao feche esta janela (ela e o servidor).
echo ============================================================
echo.
.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000

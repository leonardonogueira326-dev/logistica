@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Modo servidor: outros PCs da rede da empresa acessam pelo navegador.
if not exist .venv\Scripts\python.exe (
  echo Rode instalar.bat primeiro.
  pause & exit /b 1
)
set LOGISTICA_OLLAMA_MODEL=qwen2.5:3b

echo Preparando as telas...
pushd route-genius-main
call npm run build >nul 2>&1 || (popd & echo [ERRO] Falha ao compilar as telas. & pause & exit /b 1)
popd

echo.
echo ============================================================
echo  Sistema de logistica no ar. Nos outros PCs, abra no navegador:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo     http://%%a:8000
echo  Se o Windows perguntar sobre o Firewall, clique em "Permitir".
echo  Nao feche esta janela (ela e o servidor).
echo ============================================================
echo.
.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000

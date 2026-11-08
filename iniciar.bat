@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Rode instalar.bat primeiro.
  pause & exit /b 1
)

rem IA local: troque o modelo aqui se quiser testar outro (ex.: qwen2.5:7b)
set LOGISTICA_OLLAMA_MODEL=qwen2.5:3b

echo Preparando as telas (leva alguns segundos)...
pushd route-genius-main
call npm run build >nul 2>&1 || (popd & echo [ERRO] Falha ao compilar as telas. Rode instalar.bat. & pause & exit /b 1)
popd

echo Sistema em http://localhost:8000  (feche esta janela para desligar)
start "" http://localhost:8000
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000

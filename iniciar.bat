@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Rode instalar.bat primeiro.
  pause & exit /b 1
)

rem IA local: troque o modelo aqui se quiser testar outro (ex.: qwen2.5:7b)
set LOGISTICA_OLLAMA_MODEL=qwen2.5:3b

start "Logistica - API (nao feche)" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000"
start "Logistica - Tela (nao feche)" cmd /k "cd route-genius-main && npm run dev -- --port 5173"

echo Iniciando... o navegador abre em alguns segundos.
timeout /t 8 /nobreak >nul
start "" http://localhost:5173

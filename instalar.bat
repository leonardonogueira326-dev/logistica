@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Superfine Logistica - instalacao
echo ============================================

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (
  echo [ERRO] Python nao encontrado. Instale o Python 3.10+ em https://www.python.org/downloads/
  echo        e marque "Add python.exe to PATH" durante a instalacao.
  pause & exit /b 1
)
where npm >nul 2>nul || (
  echo [ERRO] Node.js nao encontrado. Instale o Node 20+ em https://nodejs.org/
  pause & exit /b 1
)

echo.
echo [1/3] Ambiente Python (.venv)...
if not exist .venv\Scripts\python.exe %PY% -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt pytest -q || (echo [ERRO] pip install falhou & pause & exit /b 1)

echo.
echo [2/3] Tela (frontend React)...
pushd route-genius-main
call npm install --no-audit --no-fund || (popd & echo [ERRO] npm install falhou & pause & exit /b 1)
popd

echo.
echo [3/3] IA local (Ollama)...
where ollama >nul 2>nul && (
  echo Baixando o modelo qwen2.5:3b - cerca de 2 GB, so na primeira vez...
  ollama pull qwen2.5:3b
) || (
  echo [AVISO] Ollama nao encontrado. O sistema funciona sem IA; para ativar,
  echo         instale em https://ollama.com e rode este instalador de novo.
)

echo.
echo Pronto! Para usar, de dois cliques em iniciar.bat
pause

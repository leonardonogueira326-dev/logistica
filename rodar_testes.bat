@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Para testar com PDFs reais, copie-os para a pasta dados_teste\ (nao vai para o GitHub)
.venv\Scripts\python.exe -m pytest -q tests
pause

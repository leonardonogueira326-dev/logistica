@echo off
rem Mantem o sistema ligado e atualizado sozinho (aberto pelo Windows ao entrar no usuario).
rem Para desligar: feche esta janela. Para nao abrir mais sozinho: remover_inicio_automatico.bat
title Logistica - ligado (pode minimizar, nao feche)
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe exit /b 1
:de_novo
.venv\Scripts\python.exe scripts\vigia.py
if not errorlevel 1 exit
rem 75 = o vigia se atualizou; outro erro = caiu: espera 10s e abre de novo
if not errorlevel 75 ping -n 11 127.0.0.1 >nul
goto de_novo

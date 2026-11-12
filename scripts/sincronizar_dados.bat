@echo off
rem ============================================================
rem  Sincroniza os DADOS da operacao com o repositorio PRIVADO
rem  logistica-dados (base de clientes, aprendizado, quadros).
rem  O codigo fica no repositorio publico; os dados nunca vao para ele.
rem  Chamado pelo iniciar.bat e pelo sincronizar.bat.
rem ============================================================
cd /d "%~dp0.."
where git >nul 2>&1 || exit /b 0
if not exist .git-dados exit /b 0

set "G=git --git-dir=.git-dados --work-tree=."
set "PASTAS=base-de-clientes*.xlsx base-transportadoras*.xlsx data\*.json data\sessions data\historico dados_teste"

echo Sincronizando dados com o GitHub privado...
for %%p in (%PASTAS%) do %G% add -A -f -- "%%p" >nul 2>&1
%G% diff --cached --quiet || %G% commit -q -m "Dados de %COMPUTERNAME% em %date% %time:~0,5%"

%G% pull -q --rebase origin main >nul 2>&1
if errorlevel 1 (
  %G% rebase --abort >nul 2>&1
  echo.
  echo [ATENCAO] Os dados deste PC e os da nuvem mudaram ao mesmo tempo.
  echo Nada foi perdido, mas a sincronizacao parou. Chame o Claude para resolver.
  echo.
  exit /b 1
)
%G% push -q origin main >nul 2>&1 || echo [ATENCAO] Nao consegui enviar os dados (internet ou login do GitHub).
exit /b 0

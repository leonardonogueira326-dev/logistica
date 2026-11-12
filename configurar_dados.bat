@echo off
chcp 65001 >nul
rem ============================================================
rem  Liga este PC ao repositorio PRIVADO de dados (uma vez por PC).
rem  - 1o PC (que ja tem os dados): envia para a nuvem.
rem  - PCs seguintes: baixam os dados da nuvem.
rem ============================================================
cd /d "%~dp0"
where git >nul 2>&1 || (
  echo Git nao encontrado. Instale em https://git-scm.com/download/win e rode de novo.
  pause & exit /b 1
)
if exist .git-dados (
  echo Este PC ja esta ligado aos dados. Use sincronizar.bat.
  pause & exit /b 0
)
set "REPO=https://github.com/leonardonogueira326-dev/logistica-dados.git"
set "G=git --git-dir=.git-dados --work-tree=."
set "PASTAS=base-de-clientes*.xlsx base-transportadoras*.xlsx data\*.json data\sessions data\historico dados_teste"

%G% init -q
%G% config user.name "%COMPUTERNAME%"
%G% config user.email "logistica@%COMPUTERNAME%.local"
%G% remote add origin %REPO%

git ls-remote --heads %REPO% main | findstr main >nul
if errorlevel 1 (
  echo Primeiro PC: enviando os dados deste PC para o GitHub privado...
  %G% checkout -q -b main
  for %%p in (%PASTAS%) do %G% add -A -f -- "%%p" >nul 2>&1
  %G% commit -q -m "Dados iniciais de %COMPUTERNAME%"
  %G% push -q -u origin main || (echo [ERRO] Nao consegui enviar. Confira o login do GitHub. & pause & exit /b 1)
) else (
  echo Baixando os dados do GitHub privado...
  %G% fetch -q origin main || (echo [ERRO] Nao consegui baixar. Confira o login do GitHub. & pause & exit /b 1)
  %G% checkout -q -f -B main origin/main
)
echo.
echo Pronto: este PC esta ligado aos dados. O iniciar.bat sincroniza sozinho.
pause

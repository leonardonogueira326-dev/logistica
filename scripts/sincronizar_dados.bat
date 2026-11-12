@echo off
rem ============================================================
rem  Sincroniza os DADOS da operacao com o repositorio PRIVADO
rem  logistica-dados (base de clientes, aprendizado, quadros).
rem  O codigo fica no repositorio publico; os dados nunca vao para ele.
rem  Chamado pelo iniciar.bat e pelo sincronizar.bat.
rem  Erros do git ficam em logs\sincronizacao.log.
rem ============================================================
cd /d "%~dp0.."
where git >nul 2>&1 || exit /b 0
if not exist logs mkdir logs
set "SLOG=logs\sincronizacao.log"
echo ==== %date% %time% %COMPUTERNAME% ==== >> "%SLOG%"

rem O sistema roda sempre a main (as outras branches sao de desenvolvimento).
rem So troca se a main ja contem tudo desta branch (nada se perde).
for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set "RAMO=%%b"
if /i not "%RAMO%"=="main" (
  git fetch -q origin main >> "%SLOG%" 2>&1
  git merge-base --is-ancestor HEAD origin/main >> "%SLOG%" 2>&1 && (
    echo Passando o codigo para a versao principal ^(main^)...
    echo ramo %RAMO% -^> main >> "%SLOG%"
    git checkout -q -B main origin/main >> "%SLOG%" 2>&1
    git branch -q --set-upstream-to=origin/main main >> "%SLOG%" 2>&1
  )
)

if not exist .git-dados exit /b 0

set "G=git --git-dir=.git-dados --work-tree=."
set "PASTAS=base-de-clientes*.xlsx base-transportadoras*.xlsx data\*.json data\sessions data\historico dados_teste"

echo Sincronizando dados com o GitHub privado...
for %%p in (%PASTAS%) do %G% add -A -f -- "%%p" >nul 2>&1
%G% diff --cached --quiet || %G% commit -q -m "Dados de %COMPUTERNAME% em %date% %time:~0,5%"

%G% pull -q --rebase origin main >> "%SLOG%" 2>&1
if errorlevel 1 (
  %G% status --short --untracked-files=no >> "%SLOG%" 2>&1
  %G% rebase --abort >nul 2>&1
  echo.
  echo [ATENCAO] Nao consegui sincronizar os dados agora. Nada foi perdido.
  echo Detalhes em logs\sincronizacao.log - chame o Claude se repetir.
  echo.
  exit /b 1
)
%G% push -q origin main >> "%SLOG%" 2>&1 || echo [ATENCAO] Nao consegui enviar os dados (internet ou login do GitHub).
exit /b 0

@echo off
rem ============================================================
rem  Sincroniza os DADOS da operacao com o repositorio PRIVADO
rem  logistica-dados (base de clientes, aprendizado, quadros).
rem  O codigo fica no repositorio publico; os dados nunca vao para ele.
rem  Chamado pelo iniciar.bat, pelo sincronizar.bat e pelo botao
rem  "Sincronizar agora" do sistema.
rem  - Erros do git: logs\sincronizacao.log
rem  - Resultado (a tela mostra): logs\sincronizacao_status.txt
rem  - Conflito (mesmo arquivo mexido nos dois PCs): fica a versao deste PC;
rem    a da nuvem vai para logs\conflitos\
rem ============================================================
cd /d "%~dp0.."
where git >nul 2>&1 || exit /b 0
if not exist logs mkdir logs
set "SLOG=logs\sincronizacao.log"
set "STATUS=logs\sincronizacao_status.txt"
set "AGORA=%date% %time:~0,5%"
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
rem dentro de for /f ('...') o "=" precisa de ^
set "GF=git --git-dir^=.git-dados --work-tree^=."
set "PASTAS=base-de-clientes*.xlsx base-representantes*.xlsx base-transportadoras*.xlsx data\*.json data\sessions data\historico dados_teste"

echo Sincronizando dados com o GitHub privado...
for %%p in (%PASTAS%) do %G% add -A -f -- "%%p" >nul 2>&1
%G% diff --cached --quiet || %G% commit -q -m "Dados de %COMPUTERNAME% em %AGORA%"

rem Arquivo que nao e dado da operacao (leia-me, script, diagnostico) alterado
rem aqui travava o download: volta para a versao do repositorio.
for /f "delims=" %%f in ('%GF% diff --name-only') do (
  echo descartando alteracao local em %%f ^(nao e dado da operacao^) >> "%SLOG%"
  %G% checkout -- "%%f" >> "%SLOG%" 2>&1
)

set "CONFLITO="
rem Internet oscilando: tenta ate 3 vezes antes de dar erro
set /a TENTATIVA=0
:baixar
set /a TENTATIVA+=1
%G% pull -q --rebase origin main >> "%SLOG%" 2>&1
if not errorlevel 1 goto enviar
if exist .git-dados\rebase-merge goto conflito
if exist .git-dados\rebase-apply goto conflito
if %TENTATIVA% GEQ 3 goto falhou
echo tentando de novo em 10s ^(%TENTATIVA%/3^) >> "%SLOG%"
ping -n 11 127.0.0.1 >nul
goto baixar

:conflito

rem ---------- conflito: fica a versao deste PC, a da nuvem vai para logs\conflitos
set /a VOLTAS=0
:resolver
set /a VOLTAS+=1
if %VOLTAS% GTR 30 goto desiste
if not exist logs\conflitos mkdir logs\conflitos
for /f "delims=" %%f in ('%GF% diff --name-only --diff-filter^=U') do call :manter_deste_pc "%%f"
%G% -c core.editor=true rebase --continue >> "%SLOG%" 2>&1
if exist .git-dados\rebase-merge goto resolver
if exist .git-dados\rebase-apply goto resolver
goto enviar

:desiste
%G% rebase --abort >nul 2>&1
:falhou
%G% status --short --untracked-files=no >> "%SLOG%" 2>&1
> "%STATUS%" echo ERRO^|%AGORA%^|Nao consegui baixar os dados da nuvem (internet ou login do GitHub). Os dados deste PC nao foram enviados.
echo.
echo [ATENCAO] Nao consegui sincronizar os dados agora. Nada foi perdido.
echo Detalhes em logs\sincronizacao.log - chame o Claude se repetir.
echo.
exit /b 1

:enviar
%G% push -q origin main >> "%SLOG%" 2>&1
if errorlevel 1 (
  ping -n 11 127.0.0.1 >nul
  %G% push -q origin main >> "%SLOG%" 2>&1
)
if errorlevel 1 (
  > "%STATUS%" echo ERRO^|%AGORA%^|Recebi os dados da nuvem, mas nao consegui enviar os deste PC ^(internet ou login do GitHub^).
  echo [ATENCAO] Nao consegui enviar os dados ^(internet ou login do GitHub^).
  exit /b 1
)
if defined CONFLITO (
  > "%STATUS%" echo CONFLITO^|%AGORA%^|Os dois PCs mexeram no mesmo arquivo: ficou a versao deste PC; a outra esta em logs\conflitos.
) else (
  > "%STATUS%" echo OK^|%AGORA%^|Dados enviados e recebidos.
)
exit /b 0


rem ---------- conflito num arquivo: guarda a versao da nuvem e fica a deste PC
:manter_deste_pc
set "CONFLITO=1"
set "ARQ=%~1"
set "ARQ=%ARQ:/=_%"
echo conflito em %~1 - fica a versao deste PC; a da nuvem: logs\conflitos\%ARQ%.nuvem-%VOLTAS% >> "%SLOG%"
%G% show ":2:%~1" > "logs\conflitos\%ARQ%.nuvem-%VOLTAS%" 2>> "%SLOG%"
%G% checkout --theirs -- "%~1" >> "%SLOG%" 2>&1 || %G% rm -q -- "%~1" >> "%SLOG%" 2>&1
%G% add -f -- "%~1" >> "%SLOG%" 2>&1
exit /b 0

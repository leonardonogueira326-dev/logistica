@echo off
rem ============================================================
rem  Deixa o CODIGO deste PC igual a ultima versao TESTADA do GitHub
rem  (branch "estavel", que so anda quando os testes automaticos passam).
rem  Chamado pelo iniciar.bat e pelo sincronizar.bat.
rem  - Nao depende de "git pull" dar certo: busca a main e troca a
rem    pasta para ela, mesmo se este PC estiver em outra branch ou
rem    com arquivos de codigo mexidos.
rem  - Nada se perde: se este PC tiver commits que nao estao no
rem    GitHub, eles ficam guardados na branch guardado-NOMEDOPC.
rem  - Os DADOS (data\, bases) nao sao tocados aqui.
rem  - Resultado (a tela mostra): logs\codigo_status.txt
rem ============================================================

rem Roda de uma copia no TEMP: a atualizacao pode trocar este proprio arquivo.
if /i not "%~1"=="_copia" (
  copy /y "%~f0" "%TEMP%\logistica_atualizar_codigo.bat" >nul
  call "%TEMP%\logistica_atualizar_codigo.bat" _copia "%~dp0.."
  exit /b
)
cd /d "%~2"
where git >nul 2>&1 || exit /b 0
if not exist logs mkdir logs
set "CLOG=logs\codigo.log"
set "CST=logs\codigo_status.txt"
set "AGORA=%date% %time:~0,5%"
echo ==== %date% %time% %COMPUTERNAME% ==== >> "%CLOG%"

echo Buscando atualizacoes do sistema no GitHub...
git fetch -q origin main >> "%CLOG%" 2>&1
if errorlevel 1 (
  > "%CST%" echo SEMREDE^|%AGORA%^|Sem acesso ao GitHub - usando o codigo que ja estava neste PC.
  echo [AVISO] Sem acesso ao GitHub agora - seguindo com o codigo deste PC.
  exit /b 0
)

rem Versao que este PC deve rodar: "estavel" = ultima em que os testes automaticos
rem do GitHub passaram. Sem ela ainda, usa a main.
git fetch -q origin estavel >> "%CLOG%" 2>&1
set "ALVO=origin/main"
git rev-parse -q --verify origin/estavel >nul 2>&1 && set "ALVO=origin/estavel"

set "ATUAL="
for /f %%c in ('git rev-parse HEAD') do set "ATUAL=%%c"
for /f %%c in ('git rev-parse %ALVO%') do set "NUVEM=%%c"
for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set "RAMO=%%b"
if "%ATUAL%"=="%NUVEM%" if /i "%RAMO%"=="main" goto conferir_mexidos

rem Guarda o que so existe neste PC antes de trocar
git merge-base --is-ancestor HEAD %ALVO% >nul 2>&1 || (
  git branch -f "guardado-%COMPUTERNAME%" HEAD >> "%CLOG%" 2>&1
  echo commits locais guardados na branch guardado-%COMPUTERNAME% >> "%CLOG%"
)
echo Atualizando o codigo do sistema...
echo %ATUAL% ^(%RAMO%^) -^> %NUVEM% >> "%CLOG%"
git checkout -q -f -B main %ALVO% >> "%CLOG%" 2>&1
if errorlevel 1 goto erro
git branch -q --set-upstream-to=origin/main main >> "%CLOG%" 2>&1

rem Dependencias novas? (so quando mudaram)
if defined ATUAL (
  git diff --quiet %ATUAL% %NUVEM% -- requirements.txt >nul 2>&1 || (
    echo Instalando bibliotecas novas do Python...
    .venv\Scripts\python.exe -m pip install -r requirements.txt -q >> "%CLOG%" 2>&1
  )
  git diff --quiet %ATUAL% %NUVEM% -- route-genius-main/package.json route-genius-main/package-lock.json >nul 2>&1 || call :npm_install
)
goto ok

:conferir_mexidos
rem Mesmo commit, mas algum arquivo de codigo foi mexido aqui? Volta ao do GitHub.
git diff --quiet HEAD >nul 2>&1 && goto ok
echo arquivos de codigo mexidos neste PC - voltando ao do GitHub: >> "%CLOG%"
git diff --name-only HEAD >> "%CLOG%" 2>&1
git checkout -q -f -B main %ALVO% >> "%CLOG%" 2>&1
if errorlevel 1 goto erro

:ok
for /f %%c in ('git rev-parse --short HEAD') do set "CURTO=%%c"
> "%CST%" echo OK^|%AGORA%^|%CURTO%
exit /b 0

:erro
> "%CST%" echo ERRO^|%AGORA%^|Nao consegui atualizar o codigo - detalhes em logs\codigo.log
echo.
echo [ERRO] Nao consegui atualizar o codigo deste PC. Detalhes em logs\codigo.log
exit /b 1

:npm_install
echo Instalando componentes novos da tela (pode levar alguns minutos)...
set "NPMCA="
if exist "%LOCALAPPDATA%\logistica-ca\raizes-windows.pem" set "NPMCA=--cafile=%LOCALAPPDATA%\logistica-ca\raizes-windows.pem"
pushd route-genius-main
for /l %%i in (1,1,3) do (
  call npm install --no-audit --no-fund %NPMCA% >> "..\%CLOG%" 2>&1 && (popd & exit /b 0)
  ping -n 6 127.0.0.1 >nul
)
popd
echo [AVISO] npm install falhou - veja logs\codigo.log >> "%CLOG%"
exit /b 0

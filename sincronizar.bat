@echo off
chcp 65001 >nul
rem Use antes de trocar de PC: puxa o codigo novo e sincroniza os dados.
cd /d "%~dp0"
rem 1) codigo primeiro (a correcao da sincronizacao pode estar nele)
where git >nul 2>&1 && git pull -q --ff-only >nul 2>&1
call scripts\atualizar_codigo.bat
rem 2) dados: envia os deste PC e recebe os do outro
call scripts\sincronizar_dados.bat
if errorlevel 1 (
  echo.
  echo ============================================================
  echo  ATENCAO: a sincronizacao NAO deu certo.
  echo  Os dados deste PC NAO foram para o outro PC.
  echo  Nao desligue achando que subiu - chame o Claude.
  echo ============================================================
  pause
  exit /b 1
)
echo.
echo Sincronizado. Pode desligar este PC e continuar no outro.
pause

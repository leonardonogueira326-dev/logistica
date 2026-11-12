@echo off
chcp 65001 >nul
rem Use antes de trocar de PC: envia os dados e puxa o codigo novo.
cd /d "%~dp0"
call scripts\sincronizar_dados.bat
where git >nul 2>&1 && git pull -q --ff-only >nul 2>&1
echo.
echo Sincronizado. Pode desligar este PC e continuar no outro.
pause

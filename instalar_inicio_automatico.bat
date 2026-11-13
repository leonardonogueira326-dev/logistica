@echo off
rem Faz o sistema ligar sozinho quando voce entra no Windows (so no seu usuario, sem administrador).
rem Cria: 1) um arquivo na pasta Inicializar  2) o atalho "Logistica" na Area de Trabalho.
rem Para desfazer: remover_inicio_automatico.bat
chcp 65001 >nul
cd /d "%~dp0"
set "INI=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%INI%" mkdir "%INI%"
> "%INI%\Logistica.bat" echo @start "Logistica" /min "%~dp0ligar_sozinho.bat"
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "AREA=%%d"
if not defined AREA set "AREA=%USERPROFILE%\Desktop"
> "%AREA%\Logistica.url" echo [InternetShortcut]
>> "%AREA%\Logistica.url" echo URL=http://localhost:8000
echo.
echo Pronto. O sistema vai ligar sozinho ao entrar no Windows.
echo Ligando agora (janela minimizada)...
start "Logistica" /min "%~dp0ligar_sozinho.bat"
echo Em cerca de 1 minuto abra o atalho "Logistica" na Area de Trabalho.
ping -n 6 127.0.0.1 >nul

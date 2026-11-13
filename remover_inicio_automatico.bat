@echo off
rem Desfaz o instalar_inicio_automatico.bat (o sistema volta a abrir so pelo iniciar.bat).
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Logistica.bat" 2>nul
echo Removido. O sistema nao liga mais sozinho. (Se estiver ligado agora, feche a janela "Logistica - ligado".)
pause

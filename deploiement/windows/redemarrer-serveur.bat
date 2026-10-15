@echo off
rem Redémarre le serveur FSU Caisse (à lancer en administrateur).
schtasks /End /TN "FSU Caisse - Serveur"
timeout /t 2 /nobreak >nul
schtasks /Run /TN "FSU Caisse - Serveur"
pause

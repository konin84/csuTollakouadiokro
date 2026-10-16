@echo off
rem Redémarre le serveur CSU Caisse (à lancer en administrateur).
schtasks /End /TN "CSU Caisse - Serveur"
timeout /t 2 /nobreak >nul
schtasks /Run /TN "CSU Caisse - Serveur"
pause

@echo off
rem Lance une sauvegarde immédiate (base + justificatifs).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" manage.py sauvegarder
pause

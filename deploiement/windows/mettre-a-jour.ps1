#Requires -RunAsAdministrator
<#
  Mise à jour de FSU Caisse.
  1. Remplacez les fichiers de l'application par la nouvelle version
     (gardez le dossier « data » et le fichier « .env » !).
  2. Lancez ce script en administrateur.
#>
$ErrorActionPreference = "Continue"   # les avertissements de pip/python ne doivent pas tout arrêter
$App = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPy = Join-Path $App ".venv\Scripts\python.exe"
$Wheels = Join-Path $PSScriptRoot "wheels"
Set-Location $App

Write-Host "==> Sauvegarde avant mise à jour" -ForegroundColor Cyan
& $VenvPy manage.py sauvegarder
if ($LASTEXITCODE -ne 0) { throw "Sauvegarde impossible : mise à jour annulée." }

Write-Host "==> Arrêt du serveur" -ForegroundColor Cyan
Stop-ScheduledTask -TaskName "FSU Caisse - Serveur" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "==> Dépendances" -ForegroundColor Cyan
if (Test-Path $Wheels) { & $VenvPy -m pip install --quiet --disable-pip-version-check --no-index --find-links $Wheels -r requirements.txt }
else { & $VenvPy -m pip install --quiet --disable-pip-version-check -r requirements.txt }
if ($LASTEXITCODE -ne 0) { Start-ScheduledTask -TaskName "FSU Caisse - Serveur"; throw "Dépendances : échec. Serveur relancé sur l'ancienne version." }

Write-Host "==> Base de données" -ForegroundColor Cyan
& $VenvPy manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Migration de la base impossible. Restaurez la sauvegarde créée ci-dessus si besoin (manage.py restaurer)." }
& $VenvPy manage.py collectstatic --noinput -v 0
& $VenvPy manage.py init_fsu -v 0

Write-Host "==> Redémarrage du serveur" -ForegroundColor Cyan
Start-ScheduledTask -TaskName "FSU Caisse - Serveur"
Write-Host "Mise à jour terminée." -ForegroundColor Green

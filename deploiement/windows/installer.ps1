#Requires -RunAsAdministrator
<#
  Installation de CSU Caisse sur un PC Windows du réseau local.

  Usage (PowerShell en administrateur, depuis le dossier de l'application) :
      .\deploiement\windows\installer.ps1
      .\deploiement\windows\installer.ps1 -Port 8080 -DossierCopieSauvegarde "E:\SauvegardesCSU"
      .\deploiement\windows\installer.ps1 -FichierExcel "C:\Users\...\TABLEAU_DE_BORD_RECETTES_CSU_2026.xlsx" -Annee 2026

  Le script peut être relancé : il ne recrée que ce qui manque et ne supprime aucune donnée.
#>
param(
    [string]$Nom = "Centre de Santé Urbain (CSU) de Tollakouadiokro",
    [int]$Port = 80,
    [string]$DossierCopieSauvegarde = "",
    [string]$HeureSauvegarde = "20:00",
    [string]$FichierExcel = "",
    [int]$Annee = (Get-Date).Year
)

$ErrorActionPreference = "Stop"
$App = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Data = Join-Path $App "data"
$VenvPy = Join-Path $App ".venv\Scripts\python.exe"
$Wheels = Join-Path $PSScriptRoot "wheels"
$TacheServeur = "CSU Caisse - Serveur"
$TacheSauvegarde = "CSU Caisse - Sauvegarde"

function Etape($texte) { Write-Host ""; Write-Host "==> $texte" -ForegroundColor Cyan }
function Ok($texte) { Write-Host "    $texte" -ForegroundColor Green }
function Attention($texte) { Write-Host "    $texte" -ForegroundColor Yellow }

# Lance un programme externe : les avertissements écrits sur stderr ne doivent pas
# interrompre le script (comportement de Windows PowerShell 5.1) ; seul le code de sortie compte.
function Invoke-Native {
    $exe = $args[0]
    $rest = @($args | Select-Object -Skip 1)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $exe @rest 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $old }
}
function Invoke-Manage {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $VenvPy (Join-Path $App "manage.py") @args }
    finally { $ErrorActionPreference = $old }
    if ($LASTEXITCODE -ne 0) { throw "La commande 'manage.py $($args -join ' ')' a échoué." }
}

Set-Location $App
Write-Host "Installation de CSU Caisse dans $App" -ForegroundColor White

# 1. Python ------------------------------------------------------------------
Etape "Recherche de Python 3.12 ou plus récent"
$BasePy = $null
$candidats = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $candidats += , @("py", "-3") }
if (Get-Command python -ErrorAction SilentlyContinue) { $candidats += , @("python") }
foreach ($c in $candidats) {
    try {
        $exe = $c[0]; $extra = @($c | Select-Object -Skip 1)
        $info = @(Invoke-Native $exe @extra -c "import sys; print(sys.executable); print('%d.%d' % sys.version_info[:2])")
        if ($LASTEXITCODE -eq 0 -and $info.Count -ge 2) {
            $ver = [version]$info[1]
            if ($ver -ge [version]"3.12" -and $info[0] -notmatch "WindowsApps") { $BasePy = $info[0]; break }
        }
    } catch { }
}
if (-not $BasePy) {
    Write-Host ""
    Write-Host "Python 3.12 (ou plus récent) est introuvable." -ForegroundColor Red
    Write-Host "Installez-le depuis https://www.python.org/downloads/windows/ (programme d'installation 64 bits)," -ForegroundColor Red
    Write-Host "en cochant « Add python.exe to PATH » et « Install for all users », puis relancez ce script." -ForegroundColor Red
    exit 1
}
Ok "Python trouvé : $BasePy"

# 2. Environnement Python et dépendances ---------------------------------------
Etape "Préparation de l'environnement Python"
if (-not (Test-Path $VenvPy)) {
    Invoke-Native $BasePy -m venv (Join-Path $App ".venv") | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Impossible de créer l'environnement Python." }
}
if (Test-Path $Wheels) {
    Invoke-Native $VenvPy -m pip install --quiet --disable-pip-version-check --no-index --find-links $Wheels -r (Join-Path $App "requirements.txt") | Out-Host
} else {
    Invoke-Native $VenvPy -m pip install --quiet --disable-pip-version-check -r (Join-Path $App "requirements.txt") | Out-Host
}
if ($LASTEXITCODE -ne 0) { throw "Installation des dépendances impossible." }
Ok "Dépendances installées"

# 3. Fichier de configuration .env --------------------------------------------
Etape "Configuration"
$EnvFile = Join-Path $App ".env"
if (-not (Test-Path $EnvFile)) {
    $chars = (48..57) + (65..90) + (97..122)
    $secret = -join (1..60 | ForEach-Object { [char]($chars | Get-Random) })
    $contenu = @(
        "SECRET_KEY=$secret",
        "DEBUG=0",
        "ALLOWED_HOSTS=*",
        "PORT=$Port",
        "DATA_DIR=$Data",
        "BACKUP_COPY_DIR=$DossierCopieSauvegarde",
        "BACKUP_KEEP_DAYS=30"
    ) -join "`r`n"
    [IO.File]::WriteAllText($EnvFile, $contenu + "`r`n", (New-Object Text.UTF8Encoding $false))
    Ok "Fichier .env créé (clé secrète générée)"
} else {
    Ok "Fichier .env existant conservé"
    $Port = [int]((Get-Content $EnvFile | Where-Object { $_ -match "^PORT=" }) -replace "PORT=", "" | Select-Object -First 1)
    if (-not $Port) { $Port = 80 }
}
New-Item -ItemType Directory -Force -Path $Data | Out-Null

# 4. Base de données ------------------------------------------------------------
Etape "Base de données"
Invoke-Manage migrate --noinput -v 0
Invoke-Manage collectstatic --noinput -v 0

# Compte superviseur « konin » : mot de passe saisi ici, jamais enregistré dans un fichier.
$nbSuperviseurs = Invoke-Native $VenvPy (Join-Path $App "manage.py") shell --no-imports -c "from django.contrib.auth.models import User; print('SUPERVISEURS=%d' % User.objects.filter(groups__name='Superviseur').count())" |
    Where-Object { $_ -match "^SUPERVISEURS=" } | Select-Object -Last 1
$nbSuperviseurs = if ($nbSuperviseurs) { [int]($nbSuperviseurs -replace "SUPERVISEURS=", "") } else { 0 }
if ($nbSuperviseurs -eq 0) {
    Etape "Mot de passe du compte superviseur « konin »"
    function Lire-MotDePasse($invite) {
        $s = Read-Host $invite -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
    while ($true) {
        $mdp = Lire-MotDePasse "    Mot de passe (6 caractères minimum)"
        if ($mdp.Length -lt 6) { Attention "Trop court."; continue }
        if ($mdp -ne (Lire-MotDePasse "    Confirmer le mot de passe")) { Attention "Les deux saisies diffèrent."; continue }
        break
    }
    $env:SUPERVISEUR_MOT_DE_PASSE = $mdp
}
try { Invoke-Manage init_fsu --nom $Nom --demarrage "$Annee-01-01" }
finally { Remove-Item Env:SUPERVISEUR_MOT_DE_PASSE -ErrorAction SilentlyContinue; $mdp = $null }
Ok "Base prête : $Data\fsu_caisse.sqlite3"

$nbAdmins = Invoke-Native $VenvPy (Join-Path $App "manage.py") shell --no-imports -c "from django.contrib.auth.models import User; print('ADMINS=%d' % User.objects.filter(is_superuser=True).count())" |
    Where-Object { $_ -match "^ADMINS=" } | Select-Object -Last 1
$nbAdmins = if ($nbAdmins) { [int]($nbAdmins -replace "ADMINS=", "") } else { 0 }
if ($nbAdmins -eq 0) {
    Etape "Création du compte administrateur (gère les paramètres et les utilisateurs)"
    Invoke-Manage createsuperuser
}

if ($FichierExcel) {
    Etape "Import de l'ancien tableau Excel ($Annee)"
    Invoke-Manage import_excel $FichierExcel --annee $Annee --produits
}

# 5. Pare-feu et réseau -----------------------------------------------------------
Etape "Pare-feu Windows : ouverture du port $Port pour le réseau local"
Get-NetFirewallRule -DisplayName "CSU Caisse*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "CSU Caisse (port $Port)" -Direction Inbound -Protocol TCP -LocalPort $Port `
    -Action Allow -Profile Private, Domain | Out-Null
Ok "Règle de pare-feu créée (réseaux privés uniquement)"
foreach ($p in Get-NetConnectionProfile) {
    if ($p.NetworkCategory -eq "Public") {
        Attention "Le réseau « $($p.Name) » est classé « Public » : les autres postes ne pourront pas se connecter."
        $r = Read-Host "    Le classer en réseau « Privé » (recommandé pour le réseau du centre) ? (O/N)"
        if ($r -match "^[oOyY]") { Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private; Ok "Réseau passé en Privé" }
    }
}

Etape "Alimentation : le PC serveur ne doit pas se mettre en veille"
Invoke-Native powercfg /change standby-timeout-ac 0 | Out-Null
Invoke-Native powercfg /change hibernate-timeout-ac 0 | Out-Null
Ok "Mise en veille désactivée sur secteur"

# 6. Tâches planifiées ---------------------------------------------------------------
Etape "Démarrage automatique du serveur et sauvegarde quotidienne"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$reglages = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$action = New-ScheduledTaskAction -Execute $VenvPy -Argument "`"$App\serve.py`"" -WorkingDirectory $App
Register-ScheduledTask -TaskName $TacheServeur -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Principal $principal -Settings $reglages -Description "Serveur web CSU Caisse (réseau local)" -Force | Out-Null

$reglagesSauv = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$actionSauv = New-ScheduledTaskAction -Execute $VenvPy -Argument "`"$App\manage.py`" sauvegarder" -WorkingDirectory $App
Register-ScheduledTask -TaskName $TacheSauvegarde -Action $actionSauv `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $HeureSauvegarde) -Principal $principal -Settings $reglagesSauv `
    -Description "Sauvegarde quotidienne CSU Caisse (base + justificatifs)" -Force | Out-Null
Ok "Tâche « $TacheServeur » : démarre avec Windows"
Ok "Tâche « $TacheSauvegarde » : tous les jours à $HeureSauvegarde"

Stop-ScheduledTask -TaskName $TacheServeur -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $TacheServeur

# 7. Vérification --------------------------------------------------------------------
Etape "Vérification"
$url = if ($Port -eq 80) { "http://localhost/connexion/" } else { "http://localhost:$Port/connexion/" }
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try { if ((Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $ok = $true; break } } catch { }
}
if (-not $ok) {
    Write-Host "Le serveur ne répond pas. Consultez $Data\serveur.log et $Data\fsu_caisse.log" -ForegroundColor Red
    Write-Host "(Le port $Port est peut-être déjà utilisé : relancez avec -Port 8080)" -ForegroundColor Red
    exit 1
}
Ok "Le serveur répond."

$suffixe = if ($Port -eq 80) { "" } else { ":$Port" }
$ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch "^(127\.|169\.254\.)" } |
    Select-Object -ExpandProperty IPAddress
Write-Host ""
Write-Host "Installation terminée." -ForegroundColor Green
Write-Host "Depuis les autres postes, ouvrir dans le navigateur :" -ForegroundColor White
foreach ($ip in $ips) { Write-Host "    http://$ip$suffixe" -ForegroundColor White }
Write-Host "    ou http://$($env:COMPUTERNAME)$suffixe" -ForegroundColor White
Write-Host ""
Write-Host "Conseil : réservez l'adresse IP de ce PC dans la box/le routeur (réservation DHCP) pour qu'elle ne change pas." -ForegroundColor Yellow
Write-Host "Ensuite : connectez-vous en administrateur, ouvrez Paramètres pour créer les comptes et vérifier les tarifs." -ForegroundColor Yellow

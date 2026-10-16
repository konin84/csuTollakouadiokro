#Requires -RunAsAdministrator
<#
  Retire le démarrage automatique, la sauvegarde planifiée et la règle de pare-feu.
  Les DONNÉES (dossier data : base, justificatifs, sauvegardes) ne sont PAS supprimées.
#>
foreach ($t in @("CSU Caisse - Serveur", "CSU Caisse - Sauvegarde")) {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Get-NetFirewallRule -DisplayName "CSU Caisse*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "CSU Caisse est désactivé. Le dossier « data » a été conservé." -ForegroundColor Green

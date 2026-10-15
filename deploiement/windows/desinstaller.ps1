#Requires -RunAsAdministrator
<#
  Retire le démarrage automatique, la sauvegarde planifiée et la règle de pare-feu.
  Les DONNÉES (dossier data : base, justificatifs, sauvegardes) ne sont PAS supprimées.
#>
foreach ($t in @("FSU Caisse - Serveur", "FSU Caisse - Sauvegarde")) {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Get-NetFirewallRule -DisplayName "FSU Caisse*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "FSU Caisse est désactivé. Le dossier « data » a été conservé." -ForegroundColor Green

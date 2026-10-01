<#
.SYNOPSIS
    Cria a tarefa agendada que roda enviar_extratos.ps1 a cada N minutos.

.DESCRIPTION
    Executar como Administrador no servidor do cliente. A tarefa roda como SYSTEM,
    mesmo sem ninguem logado. O token NAO e gravado na tarefa: defina antes a variavel
    de ambiente de maquina CONCILIACAO_TOKEN (uma vez so):

        [Environment]::SetEnvironmentVariable("CONCILIACAO_TOKEN", "seu-token", "Machine")

.EXAMPLE
    .\instalar_tarefa.ps1 -ApiUrl "https://sua-api.com.br/extratos" -IntervaloMinutos 5

.EXAMPLE
    # Remover a tarefa
    Unregister-ScheduledTask -TaskName "Conciliacao - Enviar extratos" -Confirm:$false
#>
param(
    [string]$ApiUrl = "http://localhost:5000/extratos",
    [int]$IntervaloMinutos = 5,
    [string]$NomeTarefa = "Conciliacao - Enviar extratos"
)

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "enviar_extratos.ps1"

# Criar tarefa que roda como SYSTEM exige um PowerShell aberto como Administrador
$identidade = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identidade.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Execute este script em um PowerShell aberto como Administrador (clique direito > Executar como administrador)."
    exit 1
}

if (-not [Environment]::GetEnvironmentVariable("CONCILIACAO_TOKEN", "Machine")) {
    Write-Warning "A variavel de ambiente de maquina CONCILIACAO_TOKEN nao esta definida. A tarefa vai falhar ate ela existir."
}

$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -ApiUrl `"$ApiUrl`"" `
    -WorkingDirectory $PSScriptRoot
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervaloMinutos)
$usuario = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
# IgnoreNew: se uma execucao ainda estiver rodando, a proxima nao comeca em paralelo
$config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable

# -ErrorAction Stop explicito: os cmdlets de tarefa agendada (CIM) nem sempre respeitam o $ErrorActionPreference
try {
    Register-ScheduledTask -TaskName $NomeTarefa -Action $acao -Trigger $gatilho -Principal $usuario -Settings $config `
        -Description "Envia os extratos PDF de $PSScriptRoot\entrada para a API de conciliacao bancaria." `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Nao foi possivel criar a tarefa: $($_.Exception.Message)"
    exit 1
}

Write-Host "Tarefa '$NomeTarefa' criada: roda a cada $IntervaloMinutos minuto(s) e envia para $ApiUrl"
Write-Host "Log: $(Join-Path $PSScriptRoot 'enviar_extratos.log')"

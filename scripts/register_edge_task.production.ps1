<#
.SYNOPSIS
  注册 COOKIESHEEP 的生产边缘采集任务。
.DESCRIPTION
  QQ 数据库解密必须读取当前登录用户的 QQ.exe 进程内存，因此任务必须使用
  Interactive logon type，与 QQ 位于同一个用户会话。不要改成 Password/S4U/SYSTEM。
#>
param(
    [string]$TaskName = 'CsBaoyanDaily',
    [string]$Time = '06:30',
    [string]$UserId = 'wqf18',
    [string]$ScriptPath = 'D:\code\csbaoyan\daily_auto.ps1'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
    throw "Edge script not found: $ScriptPath"
}

$runAt = [datetime]::ParseExact($Time, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$escapedScriptPath = $ScriptPath.Replace('"', '\"')
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$escapedScriptPath`"" `
    -WorkingDirectory (Split-Path -Parent $ScriptPath)
$trigger = New-ScheduledTaskTrigger -Daily -At $runAt
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId $UserId `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Output "EDGE_TASK_REGISTERED name=$TaskName time=$Time user=$UserId logon=Interactive"

<#
.SYNOPSIS
  COOKIESHEEP 边缘采集任务：解密 QQ 数据、导入前一日群聊并可靠移交华为云。
.DESCRIPTION
  这是生产机 D:\code\csbaoyan\daily_auto.ps1 的受版本控制副本。日报生成、
  小红书素材生成和管理后台已经迁到华为云；本脚本不得恢复本地 LLM 处理。
  关键安全规则：qq_dump_db 非零退出时必须立即停止，绝不能继续读取旧的明文数据库，
  否则会把残缺消息误报成完整日报。
.PARAMETER Date
  目标日报日期 YYYY-MM-DD，默认使用机器本地时间的昨天。
.PARAMETER UseExistingDatabase
  仅供人工补历史数据：跳过进程内存解密，明确复用现有 nt_msg.db。
  计划任务绝不能传此参数；使用前必须确认数据库来自最近一次成功解密。
.PARAMETER ForceHandoff
  忽略本地上传成功标记并重新采集、上传。仅供人工补跑或恢复使用。
#>
param(
    [string]$Date,
    [switch]$UseExistingDatabase,
    [switch]$ForceHandoff
)

$ErrorActionPreference = "Stop"
$logDir = "D:\code\csbaoyan\logs"
$handoffDir = Join-Path $logDir "handoff"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $handoffDir | Out-Null
if (-not $Date) { $Date = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd") }
$parsedDate = [datetime]::MinValue
if (-not [datetime]::TryParseExact($Date, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsedDate)) {
    throw "日期格式无效：$Date"
}
$log = "$logDir\daily_$Date.txt"
$handoffMarker = Join-Path $handoffDir "$Date.json"

function Logm($message) {
    Add-Content -Path $log -Value ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $message)
}

function Fail($message) {
    Logm $message
    Logm "DONE"
    exit 1
}

function Ensure-QqRunning {
    if (@(Get-Process -Name "QQ" -ErrorAction SilentlyContinue).Count -gt 0) {
        return
    }

    $qqShortcuts = @(
        "C:\Users\Public\Desktop\QQ.lnk",
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\腾讯软件\QQ\QQ.lnk")
    )
    $qqShortcut = $qqShortcuts | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $qqShortcut) {
        Fail "QQ_NOT_RUNNING: 未找到 QQ 进程或启动快捷方式，请登录 Windows 后手动启动 QQ。"
    }

    Logm "QQ_NOT_RUNNING: attempting auto-start via $qqShortcut"
    Start-Process -FilePath $qqShortcut
    for ($attempt = 0; $attempt -lt 30; $attempt += 1) {
        Start-Sleep -Seconds 2
        if (@(Get-Process -Name "QQ" -ErrorAction SilentlyContinue).Count -gt 0) {
            Logm "QQ_STARTED: waiting 20 seconds for login and message sync"
            Start-Sleep -Seconds 20
            return
        }
    }
    Fail "QQ_AUTO_START_FAILED: 已尝试启动 QQ，但 60 秒内未检测到进程，请登录 Windows 后检查 QQ。"
}

Logm "START date=$Date"
if ((Test-Path -LiteralPath $handoffMarker -PathType Leaf) -and -not $ForceHandoff) {
    Logm "HANDOFF_ALREADY_COMPLETE: $handoffMarker；服务器会自行重试后续生成。人工重传请使用 -ForceHandoff。"
    Logm "DONE"
    exit 0
}
Set-Location D:\code\csbaoyan
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
$decryptedDb = "D:\code\qq_dump_db\output\2272735608\nt_msg.db"

if ($UseExistingDatabase) {
    if (-not (Test-Path -LiteralPath $decryptedDb)) {
        Fail "EXISTING_DB_NOT_FOUND: $decryptedDb"
    }
    $dbTime = (Get-Item -LiteralPath $decryptedDb).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
    Logm "step1 decrypt SKIPPED_BY_OPERATOR existing_db=$decryptedDb last_write=$dbTime"
} else {
    Ensure-QqRunning
    Logm "step1 decrypt"
    $decryptStartedAtUtc = [datetime]::UtcNow
    $decryptOutput = & "C:\Users\wqf18\miniconda3\python.exe" "D:\code\csbaoyan\scripts\edge_python_bootstrap.py" --script D:\code\qq_dump_db\dump_qq_key_auto.py --qq 2272735608 2>&1 | Out-String
    $decryptExit = $LASTEXITCODE
    $decryptTail = ($decryptOutput.Trim() -split "`n")[-1]
    Logm ("decrypt_tail: " + $decryptTail)
    if ($decryptExit -ne 0) {
        Fail "DECRYPT_FAILED (exit=$decryptExit): QQ 必须保持登录运行；已停止，未使用旧数据库生成日报。"
    }
    $freshDb = Get-Item -LiteralPath $decryptedDb -ErrorAction SilentlyContinue
    if (-not $freshDb) {
        Fail "DECRYPT_OUTPUT_MISSING: 解密命令返回成功，但未生成 $decryptedDb。"
    }
    if ($freshDb.Length -lt 1 -or $freshDb.LastWriteTimeUtc -lt $decryptStartedAtUtc.AddSeconds(-2)) {
        Fail "DECRYPT_STALE_OUTPUT: 解密命令返回成功，但 nt_msg.db 未在本次任务中刷新（last_write=$($freshDb.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))）。请确认任务与 QQ 位于同一交互登录会话。"
    }
    Logm "decrypt_output_fresh size=$($freshDb.Length) last_write=$($freshDb.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
}

Logm "step1b ingest (DB -> QCE JSON)"
$ingestOutput = & "C:\Users\wqf18\miniconda3\python.exe" "D:\code\csbaoyan\scripts\edge_python_bootstrap.py" ingest --date $Date 2>&1 | Out-String
$ingestExit = $LASTEXITCODE
Logm ("ingest_tail: " + ($ingestOutput.Trim() -split "`n")[-1])
if ($ingestExit -ne 0) { Fail "INGEST_FAILED (exit=$ingestExit)" }

Logm "step2 validate handoff payload"
$exportFile = Get-ChildItem -LiteralPath "D:\code\csbaoyan\chat_exports" -File -Filter "$Date`T*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $exportFile) { Fail "NO_QCE_EXPORT: 未找到 $Date 的 QCE JSON" }
try {
    $payload = Get-Content -LiteralPath $exportFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $messageCount = @($payload.messages).Count
    if ($messageCount -lt 1) { throw "messages 为空" }
    if (-not $payload.statistics.timeRange) { throw "缺少 statistics.timeRange" }
}
catch {
    Fail "QCE_VALIDATION_FAILED: $($_.Exception.Message)"
}
$payloadHash = (Get-FileHash -LiteralPath $exportFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
Logm "handoff_payload file=$($exportFile.Name) messages=$messageCount sha256=$payloadHash"
if ($messageCount -lt 20) { Logm "QCE_SUSPICIOUS_LOW_COUNT: only $messageCount messages; server admin will warn before publishing" }

Logm "step3 atomic handoff to Huawei cloud"
$scp = "C:\Windows\System32\OpenSSH\scp.exe"
$ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
$scpOptions = @(
    "-i", "C:\Users\wqf18\.ssh\csbaoyan_upload_key",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "UserKnownHostsFile=C:\Users\wqf18\.ssh\known_hosts",
    "-P", "6543"
)
$remotePart = "/srv/csbaoyan-daily/inbox/$Date`Tedge.json.part"
$remoteReady = "/srv/csbaoyan-daily/inbox/$Date`Tedge.json"
$uploadOutput = (& $scp @scpOptions $exportFile.FullName "root@122.9.99.104:$remotePart" 2>&1 | Out-String)
$uploadExit = $LASTEXITCODE
Logm ("scp_qce exit=" + $uploadExit + " err=" + $uploadOutput.Trim())
if ($uploadExit -ne 0) { Fail "QCE_UPLOAD_FAILED (exit=$uploadExit)" }

$sshOptions = @(
    "-i", "C:\Users\wqf18\.ssh\csbaoyan_upload_key",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "UserKnownHostsFile=C:\Users\wqf18\.ssh\known_hosts",
    "-p", "6543"
)
$activateCommand = "chgrp csbaoyan '$remotePart' && chmod 0640 '$remotePart' && mv -f '$remotePart' '$remoteReady' && systemctl start --no-block 'csbaoyan-daily@$Date.service'"
$activateOutput = (& $ssh @sshOptions "root@122.9.99.104" $activateCommand 2>&1 | Out-String)
$activateExit = $LASTEXITCODE
Logm ("activate_remote exit=" + $activateExit + " err=" + $activateOutput.Trim())
if ($activateExit -ne 0) { Fail "QCE_ACTIVATION_FAILED (exit=$activateExit); uploaded part remains for recovery" }

$marker = [ordered]@{
    date = $Date
    uploadedAt = (Get-Date).ToUniversalTime().ToString("o")
    sourceFile = $exportFile.FullName
    messageCount = $messageCount
    sha256 = $payloadHash
    destination = $remoteReady
}
[IO.File]::WriteAllText($handoffMarker, ($marker | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Logm "HANDOFF_COMPLETE: server owns report and XHS generation for $Date"

Logm "DONE"

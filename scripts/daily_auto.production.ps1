<#
.SYNOPSIS
  COOKIESHEEP 生产日报任务：解密 QQ 数据、导入前一日群聊、生成日报并上传主站。
.DESCRIPTION
  这是生产机 D:\code\csbaoyan\daily_auto.ps1 的受版本控制副本。
  关键安全规则：qq_dump_db 非零退出时必须立即停止，绝不能继续读取旧的明文数据库，
  否则会把残缺消息误报成完整日报。
.PARAMETER Date
  目标日报日期 YYYY-MM-DD，默认使用机器本地时间的昨天。
.PARAMETER UseExistingDatabase
  仅供人工补历史数据：跳过进程内存解密，明确复用现有 nt_msg.db。
  计划任务绝不能传此参数；使用前必须确认数据库来自最近一次成功解密。
#>
param(
    [string]$Date,
    [switch]$UseExistingDatabase
)

$ErrorActionPreference = "Stop"
$logDir = "D:\code\csbaoyan\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (-not $Date) { $Date = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd") }
$log = "$logDir\daily_$Date.txt"

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
Set-Location D:\code\csbaoyan
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

$modelLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^OPENAI_MODEL=" } | Select-Object -Last 1
$configuredModel = ($modelLine -replace "^OPENAI_MODEL=", "").Trim()
if ($configuredModel -in @("deepseek-chat", "deepseek-reasoner")) {
    Fail "MODEL_CONFIG_INVALID: DeepSeek 旧模型 $configuredModel 已停用，请改为 deepseek-v4-flash 或 deepseek-v4-pro。"
}

if ($UseExistingDatabase) {
    $existingDb = "D:\code\qq_dump_db\output\2272735608\nt_msg.db"
    if (-not (Test-Path -LiteralPath $existingDb)) {
        Fail "EXISTING_DB_NOT_FOUND: $existingDb"
    }
    $dbTime = (Get-Item -LiteralPath $existingDb).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
    Logm "step1 decrypt SKIPPED_BY_OPERATOR existing_db=$existingDb last_write=$dbTime"
} else {
    Ensure-QqRunning
    Logm "step1 decrypt"
    $decryptOutput = & .venv\Scripts\python.exe D:\code\qq_dump_db\dump_qq_key_auto.py --qq 2272735608 2>&1 | Out-String
    $decryptExit = $LASTEXITCODE
    $decryptTail = ($decryptOutput.Trim() -split "`n")[-1]
    Logm ("decrypt_tail: " + $decryptTail)
    if ($decryptExit -ne 0) {
        Fail "DECRYPT_FAILED (exit=$decryptExit): QQ 必须保持登录运行；已停止，未使用旧数据库生成日报。"
    }
}

Logm "step1b ingest (DB -> QCE JSON)"
$ingestOutput = & .venv\Scripts\python.exe -m csbaoyan_daily.cli ingest --date $Date 2>&1 | Out-String
$ingestExit = $LASTEXITCODE
Logm ("ingest_tail: " + ($ingestOutput.Trim() -split "`n")[-1])
if ($ingestExit -ne 0) { Fail "INGEST_FAILED (exit=$ingestExit)" }

Logm "step2 pipeline (generate -> verify -> publish)"
$pipelineOutput = & .venv\Scripts\python.exe -m csbaoyan_daily.cli pipeline --skip-commit --skip-push --date $Date 2>&1 | Out-String
$pipelineExit = $LASTEXITCODE
$pipelineText = $pipelineOutput.Trim()
$pipelineTail = $pipelineText.Substring([Math]::Max(0, $pipelineText.Length - 300))
Logm ("pipeline_tail: " + $pipelineTail)
if ($pipelineExit -ne 0) { Fail "PIPELINE_FAILED (exit=$pipelineExit)" }

$report = "pages\data\reports\$Date.md"
if (-not (Test-Path -LiteralPath $report)) {
    Fail "NO_REPORT for $Date (pipeline produced no report)"
}

Logm "step3 upload (scp to server)"
$scp = "C:\Windows\System32\OpenSSH\scp.exe"
$scpOptions = @(
    "-i", "C:\Users\wqf18\.ssh\csbaoyan_upload_key",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "UserKnownHostsFile=C:\Users\wqf18\.ssh\known_hosts",
    "-P", "6543"
)
$reportUpload = (& $scp @scpOptions $report "root@122.9.99.104:/var/www/csbaoyan/data/reports/" 2>&1 | Out-String)
$reportUploadExit = $LASTEXITCODE
Logm ("scp_report exit=" + $reportUploadExit + " err=" + $reportUpload.Trim())
if ($reportUploadExit -ne 0) { Fail "REPORT_UPLOAD_FAILED (exit=$reportUploadExit)" }

$manifestUpload = (& $scp @scpOptions "pages\data\reports.json" "root@122.9.99.104:/var/www/csbaoyan/data/" 2>&1 | Out-String)
$manifestUploadExit = $LASTEXITCODE
Logm ("scp_manifest exit=" + $manifestUploadExit + " err=" + $manifestUpload.Trim())
if ($manifestUploadExit -ne 0) { Fail "MANIFEST_UPLOAD_FAILED (exit=$manifestUploadExit)" }

Logm "DONE"

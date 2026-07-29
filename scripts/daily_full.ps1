<#
.SYNOPSIS
  路线 B 全自动每日流水线：解密本地 NTQQ 库 → ingest 导出 QCE JSON → 出日报。
.DESCRIPTION
  替代「每天手动导出聊天记录」。不创建 QQ 第二会话，纯本地操作，规避封号。
  步骤：
    1) [可选] 用 qq_dump_db 把本机 NTQQ 库解密成明文 SQLite（需 QQ 处于登录运行状态）
    2) ingest：从明文库抽取昨天目标群消息 → 写出 QCE JSON
    3) 复用现有 daily_pipeline.ps1：generate → verify → publish → broadcast
  推荐用 Windows 任务计划任务每日定时运行（见 docs/optimize-export.md）。
.PARAMETER QQ
  你的 QQ 号（传给 qq_dump_db 解密步骤）。
.PARAMETER DumpScript
  qq_dump_db 的 dump_qq_key_auto.py 路径。留空则跳过解密步骤，直接用 .env 里的 CSBAOYAN_NTQQ_DB_PATH。
.PARAMETER Date
  目标日期 YYYY-MM-DD，默认昨天。
.PARAMETER InspectOnly
  只跑体检模式（一次性字段校准用）。
.PARAMETER PipelineArgs
  透传给 daily_pipeline.ps1 的其余参数（如 --skip-push、--skip-telegram）。
#>
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$QQ,
    [string]$DumpScript,
    [string]$Date,
    [switch]$InspectOnly,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param([string]$Message) Write-Host "==> $Message" }

function Read-EnvVar {
    param([string]$Key, [string]$Default = "")
    $val = (Get-ChildItem env: | Where-Object { $_.Name -ieq $Key } | Select-Object -First 1).Value
    if ($null -eq $val) { return $Default } else { return $val }
}

function Resolve-PythonExe {
    foreach ($candidate in @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "venv\Scripts\python.exe")
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "未找到 Python，请先创建 .venv 或安装 Python。"
}

$resolvedRoot = (Resolve-Path $RepoRoot).Path
Set-Location $resolvedRoot
$python = Resolve-PythonExe
$logDir = Join-Path $resolvedRoot "logs"
[System.IO.Directory]::CreateDirectory($logDir) | Out-Null
$logPath = Join-Path $logDir ("daily_full_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

# 载入 .env（简易解析，无需额外依赖）
$envFile = Join-Path $resolvedRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $idx = $line.IndexOf("=")
            $k = $line.Substring(0, $idx).Trim()
            $v = $line.Substring($idx + 1).Trim()
            if (-not (Get-ChildItem env: | Where-Object { $_.Name -ieq $k })) {
                Set-Item -Path ("Env:" + $k) -Value $v
            }
        }
    }
}

$pythonPathPrefix = Join-Path $resolvedRoot "src"
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) { $pythonPathPrefix } else { "$pythonPathPrefix$([IO.Path]::PathSeparator)$env:PYTHONPATH" }
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

$qq = if ($QQ) { $QQ } else { Read-EnvVar "CSBAOYAN_NTQQ_QQ" }
$dateArg = if ($Date) { @("--date", $Date) } else { @() }

$exitCode = 0
$transcriptStarted = $false
try {
    Start-Transcript -Path $logPath -Append | Out-Null
    $transcriptStarted = $true
    Write-Step "日志：$logPath"
    Write-Step "Python：$python"

    # ── 步骤 1：解密（可选）──────────────────────────────────────────────
    $dumpScript = if ($DumpScript) { $DumpScript } else { Read-EnvVar "CSBAOYAN_DUMP_DB_DIR" }
    if ($dumpScript -and (Test-Path $dumpScript) -and $qq) {
        Write-Step "步骤 1/3：解密本地 NTQQ 库（qq_dump_db）"
        & $python $dumpScript --qq $qq
        if ($LASTEXITCODE -ne 0) { throw "qq_dump_db 解密失败" }
    } else {
        Write-Step "步骤 1/3：跳过解密（使用 .env 中 CSBAOYAN_NTQQ_DB_PATH 指向的已解密库）"
    }

    # ── 步骤 2：ingest ────────────────────────────────────────────────────
    if ($InspectOnly) {
        Write-Step "步骤 2/3：体检模式（不导出）"
        & $python -m csbaoyan_daily.cli ingest --inspect
    } else {
        Write-Step "步骤 2/3：ingest 导出 QCE JSON"
        & $python -m csbaoyan_daily.cli ingest @dateArg
        if ($LASTEXITCODE -ne 0) { throw "ingest 失败" }
    }

    if (-not $InspectOnly) {
        # ── 步骤 3：出日报（复用现有脚本）──────────────────────────────────
        Write-Step "步骤 3/3：generate → verify → publish → broadcast"
        $pipelineScript = Join-Path $resolvedRoot "scripts\daily_pipeline.ps1"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $pipelineScript -RepoRoot $resolvedRoot @PipelineArgs
        $exitCode = $LASTEXITCODE
    }
}
catch {
    Write-Error $_
    $exitCode = 1
}
finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
exit $exitCode

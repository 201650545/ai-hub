# watchdog_3100_alert.ps1 — :3100 网关 fail-closed 告警钩子（Claude 评审建议项）
# 单次检查（计划任务每 5 分钟调用）：
#   1. /healthz 可达 → 正常，无动作
#   2. 不可达 → 读服务状态区分 DOWN（服务已停/fail-closed 退出）vs HUNG（服务在但无响应）
#   3. 告警去抖（30 分钟内不重复）+ 写 Windows 事件日志 + 追加告警文件
$ErrorActionPreference = 'SilentlyContinue'
$svc = 'API3100Gateway'
$alertFile = 'D:\项目\data\search_gateway\failclosed_alerts.log'
$eventSrc   = 'API3100Gateway'
$dedupMin   = 30
$now = Get-Date

# --- 1. 健康检查 ---
$healthOk = $false
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:3100/healthz' -TimeoutSec 5 -UseBasicParsing
    $healthOk = ($r.StatusCode -eq 200)
} catch {
    $healthOk = $false
}
if ($healthOk) { exit 0 }

# --- 2. 去抖：距上次告警 < dedupMin 则跳过 ---
if (Test-Path $alertFile) {
    $last = (Get-Content $alertFile -Tail 1 | ForEach-Object {
        if ($_ -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})') { [datetime]$Matches[1] } }) |
        Measure-Object -Maximum
    if ($last.Maximum -and ($now - $last.Maximum).TotalMinutes -lt $dedupMin) { exit 0 }
}

# --- 3. 区分 DOWN vs HUNG ---
$svcState = (Get-Service $svc -ErrorAction SilentlyContinue).Status
if ($svcState -eq 'Running') { $kind = 'HUNG' } else { $kind = 'DOWN' }

# --- 4. 告警落盘 + 事件日志 ---
$line = "{0} [{1}] :3100 healthz 不可达, 服务状态={2}" -f $now.ToString('yyyy-MM-dd HH:mm:ss'), $kind, $svcState
try { $line | Out-File -Append -Encoding utf8 $alertFile } catch {}
try {
    if (-not [System.Diagnostics.EventLog]::SourceExists($eventSrc)) {
        [System.Diagnostics.EventLog]::CreateEventSource($eventSrc, 'Application')
    }
    Write-EventLog -LogName Application -Source $eventSrc -EventId 3105 -EntryType Error -Message $line
} catch {}

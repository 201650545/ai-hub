<#
    ModelScope 每日魔粒守护 —— 计划任务入口

    作用：定位 node、调用「魔粒守护.js」、把输出追加到 logs\task.out.log，
          并把子脚本的退出码透传给任务计划程序（便于在任务历史里看成败）。

    退出码约定（与 魔粒守护.js 一致）：
      0 = 每日魔粒已全部到账
      1 = 已连通但部分项未到账（建议人工核查）
      2 = opencli 桥接不可用（Chrome 未开或扩展离线）
      3 = 登录态失效（需手动在本地 Chrome 登录一次魔搭）
#>

$ErrorActionPreference = 'Continue'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$LogDir = Join-Path $Root 'logs'
if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir 'task.out.log'

# 定位 node：优先 PATH，其次常见安装位置
$NodeExe = $null
$cmd = Get-Command node -ErrorAction SilentlyContinue
if ($cmd) {
    $NodeExe = $cmd.Source
} else {
    $candidates = @(
        'D:\Program Files\nodejs\node.exe',
        'C:\Program Files\nodejs\node.exe',
        "$env:USERPROFILE\.workbuddy\binaries\node\versions\22.22.2\node.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { $NodeExe = $c; break }
    }
}

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -LiteralPath $LogFile -Value "" -Encoding UTF8
Add-Content -LiteralPath $LogFile -Value "===== run at $stamp =====" -Encoding UTF8

if (-not $NodeExe) {
    Add-Content -LiteralPath $LogFile -Value "FATAL: node.exe not found" -Encoding UTF8
    exit 4
}

$Script = Join-Path $Root '魔粒守护.js'
if (-not (Test-Path -LiteralPath $Script)) {
    Add-Content -LiteralPath $LogFile -Value "FATAL: 魔粒守护.js not found" -Encoding UTF8
    exit 5
}

$output = & $NodeExe $Script 2>&1
$rc = $LASTEXITCODE

$output | ForEach-Object { Add-Content -LiteralPath $LogFile -Value $_ -Encoding UTF8 }
Add-Content -LiteralPath $LogFile -Value "exit code: $rc" -Encoding UTF8

exit $rc

# ============================================================
# CherryStudio 日志自动清理脚本
# 用途：每周清理 CherryStudio 膨胀的 logs 日志 + Crashpad 崩溃转储
# 说明：
#   - 只删除 logs/ 下的旋转日志与 Crashpad 转储，不影响对话/配置数据
#   - CherryStudio 运行时自动重建日志文件，安全
# 用法：powershell -ExecutionPolicy Bypass -File 本脚本
# ============================================================

$ErrorActionPreference = 'SilentlyContinue'

# 目标用户：默认取当前账户，找不到 CherryStudio 时尝试常见用户目录
$user = $env:USERNAME
$cherryRoot = "$env:APPDATA\CherryStudio"

if (-not (Test-Path $cherryRoot)) {
    # 尝试遍历 C:\Users 下所有用户目录找 CherryStudio
    Get-ChildItem "C:\Users" -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $candidate = Join-Path $_.FullName "AppData\Roaming\CherryStudio"
        if (Test-Path $candidate) {
            $cherryRoot = $candidate
            $user = $_.Name
        }
    }
}

if (-not (Test-Path $cherryRoot)) {
    Write-Output "[skip] CherryStudio 数据目录不存在: $cherryRoot"
    exit 0
}
Write-Output "[info] 目标用户: $user, 目录: $cherryRoot"

$freedMB = 0

# ---------- 1. 清理 logs 目录（旋转日志） ----------
$logsDir = Join-Path $cherryRoot "logs"
if (Test-Path $logsDir) {
    $before = (Get-ChildItem $logsDir -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    # 删除所有文件与子目录（当前正在写的日志若被占用会跳过，不影响下次清理）
    Get-ChildItem $logsDir -Force -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    $after = (Get-ChildItem $logsDir -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    $freedMB += [math]::Round(($before - $after) / 1MB, 1)
    Write-Output ("[ok] logs: 释放 {0} MB" -f [math]::Round(($before - $after) / 1MB, 1))
}

# ---------- 2. 清理 Crashpad（崩溃转储） ----------
$crashDir = Join-Path $cherryRoot "Crashpad"
if (Test-Path $crashDir) {
    $before = (Get-ChildItem $crashDir -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    Get-ChildItem $crashDir -Force -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    $after = (Get-ChildItem $crashDir -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    $freedMB += [math]::Round(($before - $after) / 1MB, 1)
    Write-Output ("[ok] Crashpad: 释放 {0} MB" -f [math]::Round(($before - $after) / 1MB, 1))
}

# ---------- 3. 顺带清理 CherryStudio Code Cache / GPUCache（可重建的纯缓存） ----------
foreach ($sub in @("Code Cache", "GPUCache", "Cache")) {
    $p = Join-Path $cherryRoot $sub
    if (Test-Path $p) {
        $before = (Get-ChildItem $p -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum
        Get-ChildItem $p -Force -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
        $after = (Get-ChildItem $p -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum
        $freedMB += [math]::Round(($before - $after) / 1MB, 1)
        Write-Output ("[ok] {0}: 释放 {1} MB" -f $sub, [math]::Round(($before - $after) / 1MB, 1))
    }
}

Write-Output ("[done] 本次共释放 {0} MB" -f $freedMB)
<#
    注册 Windows 计划任务：ModelScope 每日魔粒守护

    设计说明
    --------
    1) 每天触发 3 次，而不是 1 次。
       原因：魔粒按【北京时间】自然日发放，而本机时区未必是 CST；
       脚本本身幂等（当日已到账则只核对不重复动作），多跑几次可以
       无脑覆盖时区偏移、开机时间不固定、网络抖动等情况。

    2) 必须在【用户已登录】的交互式会话中运行。
       原因：脚本依赖本地 Chrome 的登录 Session（opencli 浏览器桥接），
       Chrome 没在跑就没有可复用的会话。因此不能勾选"不管用户是否登录都运行"。

    3) 不需要管理员权限（RunLevel = Limited）。

    用法：
      powershell -NoProfile -ExecutionPolicy Bypass -File "注册计划任务.ps1"
#>

$ErrorActionPreference = 'Stop'

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Entry    = Join-Path $Root '运行.ps1'
$TaskName = 'ModelScope每日魔粒守护'

if (-not (Test-Path -LiteralPath $Entry)) {
    Write-Error "未找到入口脚本：$Entry"
    exit 1
}

# 触发时刻（本机时间）。如需调整，改这三个值即可。
$Times = @('09:30', '15:00', '21:00')

$Action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $Entry) `
    -WorkingDirectory $Root

$Triggers = @()
foreach ($t in $Times) {
    $Triggers += New-ScheduledTaskTrigger -Daily -At $t
}

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $Action `
    -Trigger     $Triggers `
    -Settings    $Settings `
    -Principal   $Principal `
    -Description '魔搭社区每日魔粒：登录态保活 + 250 魔粒到账核对 + 额度播报。不含点赞/评论等对外互动。' `
    -Force | Out-Null

Write-Output "已注册计划任务：$TaskName"
Write-Output "触发时刻（本机时间）：$($Times -join '、')"
Write-Output "入口：$Entry"
Write-Output ""
Write-Output "立即试跑一次： Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "查看运行结果： Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Output "卸载：         powershell -NoProfile -ExecutionPolicy Bypass -File `"$Root\卸载计划任务.ps1`""

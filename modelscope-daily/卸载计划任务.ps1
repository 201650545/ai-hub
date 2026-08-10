<#
    卸载 Windows 计划任务：ModelScope 每日魔粒守护

    只删除计划任务本身，不动脚本文件与 logs 目录。

    用法：
      powershell -NoProfile -ExecutionPolicy Bypass -File "卸载计划任务.ps1"
#>

$ErrorActionPreference = 'Stop'
$TaskName = 'ModelScope每日魔粒守护'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Output "计划任务不存在，无需卸载：$TaskName"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "已卸载计划任务：$TaskName"
Write-Output "脚本文件与 logs 目录保留在原处，未做删除。"

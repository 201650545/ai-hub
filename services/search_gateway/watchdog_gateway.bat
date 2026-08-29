@echo off
rem ===== SearchGateway watchdog - 守护 API 转发网关，确保常驻 =====
setlocal enabledelayedexpansion
:loop
rem 检查端口 3100 是否有监听
netstat -ano -p tcp | findstr ":3100" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [%date% %time%] 网关未运行，正在重启...
    schtasks /Run /TN "SearchGateway" >nul 2>&1
)
rem 每 30 秒检查一次
timeout /t 30 /nobreak >nul 2>&1
goto loop

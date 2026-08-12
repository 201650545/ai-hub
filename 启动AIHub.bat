@echo off
chcp 65001 >nul
title AI Hub 启动器
echo ========================================
echo   AI Hub 一键启动
echo ========================================
echo.

REM 1. 检查 opencli daemon
echo [1/3] 检查 opencli daemon...
curl -s http://localhost:19825/health >nul 2>&1
if %errorlevel%==0 (
    echo      opencli daemon 已在运行
) else (
    echo      启动 opencli daemon...
    start /min "opencli-daemon" opencli daemon
    timeout /t 3 /nobreak >nul
)

REM 2. Runtime CLI 统一启停（读 config/runtime.yaml）
echo [2/3] Runtime CLI 启动全部服务...
python "D:\项目\runtime\cli.py" start --all

REM 3. 状态总览
echo [3/3] 服务状态...
python "D:\项目\runtime\cli.py" status

echo.
echo ========================================
echo   启动完成！
echo   中央导航: http://localhost:8000
echo   管理面板: http://localhost:8000/dashboard/index.html
echo   搜索网关: http://localhost:3000
echo   画布观察: http://localhost:8791
echo ========================================
echo.
set /p OPEN=是否打开中央导航页面？(Y/N)
if /i "%OPEN%"=="Y" start http://localhost:8000

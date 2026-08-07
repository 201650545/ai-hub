@echo off
chcp 65001 >nul
title AI Hub 启动器
echo ========================================
echo   AI Hub 一键启动
echo ========================================
echo.

REM 1. 检查 opencli daemon
echo [1/4] 检查 opencli daemon...
curl -s http://localhost:19825/health >nul 2>&1
if %errorlevel%==0 (
    echo      opencli daemon 已在运行
) else (
    echo      启动 opencli daemon...
    start /min "opencli-daemon" opencli daemon
    timeout /t 3 /nobreak >nul
)

REM 2. 启动中央平台 :8000
echo [2/4] 启动中央平台 :8000...
curl -s http://localhost:8000/api/stats >nul 2>&1
if %errorlevel%==0 (
    echo      中央平台已在运行
) else (
    start /min "ai-hub-central" python "D:\项目\00_中央平台\server.py"
    timeout /t 3 /nobreak >nul
)

REM 3. 启动网关 ds_v4_cli :3000
echo [3/4] 启动网关 ds_v4_cli :3000...
curl -s http://localhost:3000/api/health >nul 2>&1
if %errorlevel%==0 (
    echo      网关已在运行
) else (
    start /min "ai-hub-gateway" python "D:\项目\02_网关实例\ds_v4_cli\unified_gateway.py"
    timeout /t 5 /nobreak >nul
)

REM 4. 健康巡检
echo [4/4] 健康巡检...
python "D:\项目\tests\run_all.py" --quick 2>nul || echo      （巡检脚本未运行，可手动执行 python tests\run_all.py）

echo.
echo ========================================
echo   启动完成！
echo   中央导航: http://localhost:8000
echo   管理面板: http://localhost:8000/dashboard/index.html
echo   搜索网关: http://localhost:3000
echo ========================================
echo.
set /p OPEN=是否打开中央导航页面？(Y/N)
if /i "%OPEN%"=="Y" start http://localhost:8000

# AI Hub 网关持久化启动(独立进程)
$py = "C:/Users/郭永涛/AppData/Local/Programs/Python/Python312/python.exe"
$sg = "D:/项目/services/search_gateway"
$ce = "D:/项目/services/central"

# 1. API 转发网关 (3100)
Start-Process -FilePath $py -ArgumentList "-u","api_gateway.py" -WorkingDirectory $sg -RedirectStandardOutput "$sg/logs/api_gateway.log" -RedirectStandardError "$sg/logs/api_gateway.err" -WindowStyle Hidden

# 2. 搜索网关 (3000)
Start-Process -FilePath $py -ArgumentList "-u","search_gateway.py" -WorkingDirectory $sg -RedirectStandardOutput "$sg/logs/search_gateway.log" -RedirectStandardError "$sg/logs/search_gateway.err" -WindowStyle Hidden

# 3. 中央平台 (8000)
Start-Process -FilePath $py -ArgumentList "-u","server.py" -WorkingDirectory $ce -RedirectStandardOutput "$ce/logs/server.log" -RedirectStandardError "$ce/logs/server.err" -WindowStyle Hidden

Write-Output "started 3 gateways"

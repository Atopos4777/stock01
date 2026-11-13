# 启动脚本：激活 D 盘 venv 并启动服务
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = "D:\venvs\commerce-copilot\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Error "未找到虚拟环境：$Py；请先创建或修改本脚本中的路径"
}

$env:DATA_DIR = Join-Path $Root "data"
$env:HF_HOME = "D:\hf-cache"

Set-Location $Root
Write-Host "启动 Commerce Copilot …… http://127.0.0.1:8000"
& $Py -m uvicorn app.main:app --host 127.0.0.1 --port 8000

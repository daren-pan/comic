# TaskBridge 起停脚本（Windows）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\taskbridge.ps1 start|stop|status|logs
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'logs')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot 'crawler-service\.venv\Scripts\python.exe'
$LogDir = Join-Path $RepoRoot 'logs\taskbridge'
$LogFile = Join-Path $LogDir 'service.log'
$HealthUrl = 'http://127.0.0.1:8020/healthz'

function Get-TbProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*taskbridge*run.py*' }
}

switch ($Action) {
    'start' {
        if (Get-TbProcess) { Write-Host '[taskbridge] 已在运行'; break }
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        Start-Process -FilePath $Python -ArgumentList 'tools/taskbridge/run.py' `
            -WorkingDirectory $RepoRoot -WindowStyle Hidden `
            -RedirectStandardOutput $LogFile -RedirectStandardError "$LogFile.err"
        Start-Sleep -Seconds 6
        try { Invoke-RestMethod $HealthUrl -TimeoutSec 5 | Out-Null; Write-Host '[taskbridge] 启动成功：http://127.0.0.1:8020' }
        catch { Write-Host "[taskbridge] 启动失败，看 $LogFile" }
    }
    'stop' {
        $procs = Get-TbProcess
        if (-not $procs) { Write-Host '[taskbridge] 未在运行'; break }
        $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Write-Host ('[taskbridge] 已停止 ' + $procs.Count + ' 个进程')
    }
    'status' {
        try { $h = Invoke-RestMethod $HealthUrl -TimeoutSec 5; Write-Host ('[taskbridge] 运行中 ' + ($h | ConvertTo-Json -Compress)) }
        catch { Write-Host '[taskbridge] 未运行' }
    }
    'logs' {
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 40 } else { Write-Host '还没有日志' }
    }
}

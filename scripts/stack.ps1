# 两套栈的统一编排入口（Windows）
#   Comic 栈  = deploy/docker-compose.yml           项目名 comic
#   Dify 栈   = ../dify/docker/docker-compose.yaml  项目名 docker
#
# 用法：
#   powershell -File scripts\stack.ps1 status            # 两套栈总览
#   powershell -File scripts\stack.ps1 up    [comic|dify|all]
#   powershell -File scripts\stack.ps1 down  [comic|dify|all]
#   powershell -File scripts\stack.ps1 restart [comic|dify|all]
#   powershell -File scripts\stack.ps1 logs  <服务名> [行数]
#
# 设计原则：**不改任何一方的 compose 文件**，只做统一调用与状态聚合。
# 两套栈保持独立项目名，容器/卷/网络互不干扰，升级互不影响。

param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'up', 'down', 'restart', 'logs', 'ps')]
    [string]$Action = 'status',

    [Parameter(Position = 1)]
    [string]$Target = 'all',

    [Parameter(Position = 2)]
    [string]$Extra = ''
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ComicFile = Join-Path $RepoRoot 'deploy\docker-compose.yml'
$DifyFile = Join-Path (Split-Path -Parent $RepoRoot) 'dify\docker\docker-compose.yaml'

function Get-StackDef {
    @(
        [pscustomobject]@{ Name = 'comic'; File = $ComicFile; Project = 'comic' }
        [pscustomobject]@{ Name = 'dify';  File = $DifyFile;  Project = 'docker' }
    )
}

function Invoke-Compose {
    param($Stack, [string[]]$ComposeArgs)
    & docker compose -f $Stack.File -p $Stack.Project @ComposeArgs
}

function Show-Status {
    Write-Host ''
    foreach ($s in Get-StackDef) {
        Write-Host ("== " + $s.Name + " (" + (Split-Path $s.File -Leaf) + ", project=" + $s.Project + ")") -ForegroundColor Cyan
        if (-not (Test-Path $s.File)) { Write-Host '   文件不存在'; continue }
        $rows = & docker ps -a --filter ("label=com.docker.compose.project=" + $s.Project) `
            --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>$null
        if (-not $rows) { Write-Host '   （无容器）'; continue }
        foreach ($r in $rows) {
            $p = $r -split '\|'
            $color = if ($p[1] -like 'Up*') { 'Green' } else { 'DarkYellow' }
            Write-Host ("   {0,-28} {1}" -f $p[0], $p[1]) -ForegroundColor $color
        }
    }
    Write-Host ''
    Write-Host '== 宿主端口 ==' -ForegroundColor Cyan
    $ports = @(80, 85, 86, 3000, 6099, 5300, 5401, 8000, 8020, 3309)
    foreach ($p in $ports) {
        $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        Write-Host ("   {0,-6} {1}" -f $p, $(if ($c) { 'LISTEN' } else { '-' }))
    }
}

switch ($Action) {
    'status' { Show-Status }
    'ps' { Show-Status }
    'logs' {
        if (-not $Target -or $Target -eq 'all') { throw 'logs 需要指定服务名，例如：logs comic-api' }
        $n = if ($Extra) { $Extra } else { '100' }
        & docker logs --tail $n -f $Target
    }
    default {
        $stacks = if ($Target -eq 'all') { Get-StackDef } else { Get-StackDef | Where-Object Name -eq $Target }
        if (-not $stacks) { throw "未知目标：$Target（可选 comic / dify / all）" }
        foreach ($s in $stacks) {
            Write-Host ("== " + $Action + " " + $s.Name) -ForegroundColor Cyan
            Invoke-Compose -Stack $s -ComposeArgs @($Action, '-d') 2>&1 | ForEach-Object { Write-Host ("   " + $_) }
        }
        Show-Status
    }
}

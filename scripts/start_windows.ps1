# Start FinAlly in Docker (Windows PowerShell). Idempotent.
# Usage: scripts\start_windows.ps1 [--build] [--no-open]
#   (-Build / -NoOpen also accepted)
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$NoOpen,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Continue'

foreach ($arg in $Rest) {
    switch ($arg) {
        '--build'   { $Build = $true }
        '--no-open' { $NoOpen = $true }
        default     { Write-Error "Unknown option: $arg"; exit 1 }
    }
}

$Image     = 'finally'
$Container = 'finally'
$Volume    = 'finally-data'
$Port      = 8000
$Url       = "http://localhost:$Port"

$RootDir = Split-Path -Parent $PSScriptRoot
Push-Location $RootDir
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error 'docker is not installed or not on PATH.'
        exit 1
    }

    if (-not (Test-Path '.env')) {
        if (Test-Path '.env.example') {
            Copy-Item '.env.example' '.env'
            Write-Warning '.env not found - created it from .env.example. Add your OPENROUTER_API_KEY to .env to enable the AI chat.'
        } else {
            Write-Error "Neither .env nor .env.example found in $RootDir"
            exit 1
        }
    }

    docker image inspect $Image *> $null
    $imageExists = ($LASTEXITCODE -eq 0)
    if ($Build -or -not $imageExists) {
        Write-Host "Building image '$Image'..."
        docker build -t $Image .
        if ($LASTEXITCODE -ne 0) { Write-Error 'docker build failed.'; exit 1 }
    }

    # Replace any existing container (running or stopped); the volume is kept.
    docker container inspect $Container *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Removing existing container '$Container'..."
        docker rm -f $Container | Out-Null
    }

    Write-Host "Starting container '$Container'..."
    docker run -d --name $Container -v "${Volume}:/app/db" -p "${Port}:8000" --env-file .env $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error 'docker run failed.'; exit 1 }

    Write-Host 'Waiting for FinAlly to become ready...'
    for ($i = 0; $i -lt 60; $i++) {
        try {
            Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    Write-Host "FinAlly is running at $Url"
    Write-Host 'Stop it with: scripts\stop_windows.ps1'

    if (-not $NoOpen) {
        Start-Process $Url
    }
    exit 0
} finally {
    Pop-Location
}

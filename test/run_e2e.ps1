<#
.SYNOPSIS
  Run the FinAlly Playwright E2E suite against a throwaway container.
.EXAMPLE
  ./test/run_e2e.ps1            # build image if missing, run all tests
  ./test/run_e2e.ps1 -Build     # force image rebuild
  ./test/run_e2e.ps1 -g chat    # pass extra args to playwright
  $env:BASE_URL='http://localhost:8000'; ./test/run_e2e.ps1   # skip Docker
#>
param(
  [switch]$Build,
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$PlaywrightArgs
)

$ErrorActionPreference = 'Continue'
$ScriptDir = $PSScriptRoot
$RepoRoot = Split-Path -Parent $ScriptDir
$Image = 'finally'
$Container = 'finally-e2e'
$Volume = 'finally-e2e-data'
$Port = if ($env:E2E_PORT) { $env:E2E_PORT } else { '8001' }
if (-not $PlaywrightArgs) { $PlaywrightArgs = @() }

function Remove-E2E {
  docker rm -f $Container 2>$null | Out-Null
  docker volume rm -f $Volume 2>$null | Out-Null
}

Push-Location $ScriptDir
$status = 1
try {
  if (-not (Test-Path 'node_modules/@playwright/test')) {
    Write-Host '>> Installing test dependencies'
    npm install; if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    npx playwright install chromium; if ($LASTEXITCODE -ne 0) { throw 'playwright install failed' }
  }

  if ($env:BASE_URL) {
    Write-Host ">> BASE_URL set; testing $env:BASE_URL without Docker"
    npx playwright test @PlaywrightArgs
    $status = $LASTEXITCODE
  } else {
  try {
    docker image inspect $Image 2>$null | Out-Null
    if ($Build -or $LASTEXITCODE -ne 0) {
      Write-Host ">> Building image $Image"
      docker build -t $Image $RepoRoot
      if ($LASTEXITCODE -ne 0) { throw 'docker build failed' }
    }

    Remove-E2E
    Write-Host ">> Starting $Container on port $Port (LLM_MOCK=true)"
    docker run -d --name $Container -p "${Port}:8000" -v "${Volume}:/app/db" `
      -e LLM_MOCK=true -e MASSIVE_API_KEY= -e OPENROUTER_API_KEY= $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'docker run failed' }

    $url = "http://localhost:$Port"
    Write-Host ">> Waiting for $url/api/health"
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
      try {
        $r = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
      } catch { }
      Start-Sleep -Seconds 1
    }
    if (-not $healthy) {
      Write-Host '!! App did not become healthy in 60s. Container logs:'
      docker logs $Container 2>&1 | Select-Object -Last 50
      throw 'health check timed out'
    }
    Write-Host '>> App is healthy'

    $env:BASE_URL = $url
    try {
      npx playwright test @PlaywrightArgs
      $status = $LASTEXITCODE
    } finally {
      Remove-Item Env:BASE_URL -ErrorAction SilentlyContinue
    }
    if ($status -ne 0) {
      Write-Host '>> Tests failed; last container logs:'
      docker logs $Container 2>&1 | Select-Object -Last 80
    }
  } finally {
    Write-Host ">> Tearing down $Container and $Volume"
    Remove-E2E
  }
  }
} catch {
  Write-Host "!! $_"
  $status = 1
} finally {
  Pop-Location
}
exit $status

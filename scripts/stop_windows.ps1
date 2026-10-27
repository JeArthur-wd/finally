# Stop and remove the FinAlly container (Windows PowerShell). Idempotent.
# The finally-data volume is kept, so your portfolio persists.
$ErrorActionPreference = 'Continue'

$Container = 'finally'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error 'docker is not installed or not on PATH.'
    exit 1
}

docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    docker rm -f $Container | Out-Null
    Write-Host "Stopped and removed container '$Container'. Data volume 'finally-data' kept."
} else {
    Write-Host "Container '$Container' is not running."
}

exit 0

param(
    [string]$EnvFile = ".env.local",
    [switch]$MockRunPodDelete
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing $EnvFile. Copy .env.example and fill in runtime credentials."
}

$envContents = Get-Content -LiteralPath $EnvFile -Raw
if ($envContents -match "YOUR-NEXTCLOUD-HOST|replace-with-nextcloud-app-password|replace-me") {
    throw "$EnvFile still contains placeholder credentials"
}

docker compose `
    --env-file $EnvFile `
    --file docker-compose.local.yml `
    up `
    --abort-on-container-exit `
    --exit-code-from runner

$runnerExitCode = $LASTEXITCODE
if ($MockRunPodDelete) {
    Write-Host "MOCK RunPod delete: runner exited with code $runnerExitCode"
}
exit $runnerExitCode

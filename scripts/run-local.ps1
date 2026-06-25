param(
    [string]$EnvFile = ".env.local"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$EnvFilePath = if ([System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile
} else {
    Join-Path $RepositoryRoot $EnvFile
}

if (-not (Test-Path -LiteralPath $EnvFilePath)) {
    throw "Missing $EnvFile. Copy .env.example and fill in runtime credentials."
}

$envContents = Get-Content -LiteralPath $EnvFilePath -Raw
if ($envContents -match "YOUR-NEXTCLOUD-HOST|replace-with-nextcloud-app-password|replace-me") {
    throw "$EnvFile still contains placeholder credentials"
}

docker compose `
    --env-file $EnvFilePath `
    --file "$RepositoryRoot\docker-compose.local.yml" `
    up `
    --abort-on-container-exit `
    --exit-code-from runner

exit $LASTEXITCODE

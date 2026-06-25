param(
    [string]$Repository = "ghcr.io/keinniemand/factory-cloud-runner"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$tag = "${Repository}:bootstrap"

Write-Host "Publishing tiny GHCR bootstrap image as $tag"
docker buildx build `
    --progress plain `
    --platform linux/amd64 `
    --file "$RepositoryRoot\docker\Dockerfile.bootstrap" `
    --tag $tag `
    --push `
    $RepositoryRoot

if ($LASTEXITCODE -ne 0) {
    throw "GHCR bootstrap push failed"
}

Write-Host "Now make the package public in GitHub Package settings before pushing the full image:"
Write-Host "https://github.com/users/KeinNiemand/packages/container/factory-cloud-runner/settings"

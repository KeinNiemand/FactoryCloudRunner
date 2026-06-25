param(
    [string]$LlamaFactoryPath = "A:\AI\LlamaFactory",
    [string]$Tag = "factory-cloud-runner:local",
    [switch]$Production,
    [switch]$Push,
    [switch]$PackageIsPublic,
    [string]$Platform = "linux/amd64"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath "$LlamaFactoryPath\pyproject.toml")) {
    throw "LlamaFactory repository not found at $LlamaFactoryPath"
}

if ($Platform -ne "linux/amd64") {
    throw "FactoryCloudRunner supports only linux/amd64 (RunPod and the pinned FA2 wheel are x86_64)"
}

if ($Push -and -not $Production) {
    throw "Pushing requires -Production so both source trees are verified clean"
}

if ($Push -and -not $PackageIsPublic) {
    throw "Refusing to upload the full image until GHCR is public. Bootstrap it, change visibility, then pass -PackageIsPublic."
}

$commit = (git -C $LlamaFactoryPath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) {
    throw "Could not resolve the LlamaFactory commit at $LlamaFactoryPath"
}

$dirtyOutput = @(
    git -C $LlamaFactoryPath status --porcelain --untracked-files=all |
        Where-Object { $_ -notmatch '^\?\? \.codex/' }
)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the LlamaFactory working tree at $LlamaFactoryPath"
}
$dirty = $dirtyOutput.Count -gt 0

if ($Production -and $dirty) {
    throw "Production images require a clean LlamaFactory working tree. Current revision: $commit"
}

if ($Production) {
    $runnerCommit = (git -C $RepositoryRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $runnerCommit) {
        throw "Production images require a committed FactoryCloudRunner revision"
    }
    $runnerDirty = @(git -C $RepositoryRoot status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $runnerDirty.Count -gt 0) {
        throw "Production images require a clean FactoryCloudRunner working tree. Current revision: $runnerCommit"
    }
}

$dirtyFlag = if ($dirty) { "1" } else { "0" }
$output = if ($Push) { "--push" } else { "--load" }
Write-Host "Building $Tag for $Platform from LlamaFactory $commit (dirty=$dirtyFlag)"

docker buildx build `
    --progress plain `
    --platform $Platform `
    --file "$RepositoryRoot\docker\Dockerfile" `
    --build-context "llamafactory=$LlamaFactoryPath" `
    --build-arg "LLAMAFACTORY_COMMIT=$commit" `
    --build-arg "LLAMAFACTORY_DIRTY=$dirtyFlag" `
    --tag $Tag `
    $output `
    $RepositoryRoot

if ($LASTEXITCODE -ne 0) {
    throw "Docker build failed"
}

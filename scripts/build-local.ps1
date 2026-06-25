param(
    [string]$LlamaFactoryPath = "A:\AI\LlamaFactory",
    [string]$Tag = "factory-cloud-runner:local",
    [switch]$Production
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath "$LlamaFactoryPath\pyproject.toml")) {
    throw "LlamaFactory repository not found at $LlamaFactoryPath"
}

$commit = (git -C $LlamaFactoryPath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) {
    throw "Could not resolve the LlamaFactory commit at $LlamaFactoryPath"
}

$dirtyOutput = @(git -C $LlamaFactoryPath status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the LlamaFactory working tree at $LlamaFactoryPath"
}
$dirty = $dirtyOutput.Count -gt 0

if ($Production -and $dirty) {
    throw "Production images require a clean LlamaFactory working tree. Current revision: $commit"
}

if ($Production) {
    $runnerCommit = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $runnerCommit) {
        throw "Production images require a committed FactoryCloudRunner revision"
    }
    $runnerDirty = @(git status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $runnerDirty.Count -gt 0) {
        throw "Production images require a clean FactoryCloudRunner working tree. Current revision: $runnerCommit"
    }
}

$dirtyFlag = if ($dirty) { "1" } else { "0" }
Write-Host "Building $Tag from LlamaFactory $commit (dirty=$dirtyFlag)"

docker buildx build `
    --progress plain `
    --file docker/Dockerfile `
    --build-context "llamafactory=$LlamaFactoryPath" `
    --build-arg "LLAMAFACTORY_COMMIT=$commit" `
    --build-arg "LLAMAFACTORY_DIRTY=$dirtyFlag" `
    --tag $Tag `
    --load `
    .

if ($LASTEXITCODE -ne 0) {
    throw "Docker build failed"
}

param(
    [string]$Image = "factory-cloud-runner:local",
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$suffix = "$PID"
$network = "fcr-smoke-$suffix"
$server = "fcr-webdav-$suffix"
$runner = "fcr-runner-$suffix"
$hfCache = "fcr-hf-$suffix"
$torchCache = "fcr-torch-$suffix"
$compiledCache = "fcr-compiled-$suffix"
$root = Join-Path ([IO.Path]::GetTempPath()) "factory-cloud-runner-smoke-$suffix"
$remote = Join-Path $root "remote"
$runDir = Join-Path $remote "training_artifacts\run9901"
$dataDir = Join-Path $remote "training_data\smoke"
$tlsDir = Join-Path $root "tls"

function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed: docker $args"
    }
}

try {
    New-Item -ItemType Directory -Force $runDir, $dataDir, $tlsDir | Out-Null

    $rsa = [Security.Cryptography.RSA]::Create(2048)
    $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        "CN=webdav",
        $rsa,
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1
    )
    $san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $san.AddDnsName("webdav")
    $request.CertificateExtensions.Add($san.Build())
    $certificate = $request.CreateSelfSigned(
        [DateTimeOffset]::UtcNow.AddMinutes(-1),
        [DateTimeOffset]::UtcNow.AddDays(1)
    )
    [IO.File]::WriteAllText((Join-Path $tlsDir "cert.pem"), $certificate.ExportCertificatePem())
    [IO.File]::WriteAllText((Join-Path $tlsDir "key.pem"), $rsa.ExportPkcs8PrivateKeyPem())

    @'
model_name_or_path: HuggingFaceTB/SmolLM2-135M-Instruct
template: smollm2
trust_remote_code: false
flash_attn: fa2
use_unsloth: true
enable_liger_kernel: true
stage: sft
do_train: true
finetuning_type: lora
lora_rank: 8
lora_alpha: 8
lora_dropout: 0
lora_target: all
loraplus_lr_ratio: 4.6
dataset_dir: /workspace/data/smoke
dataset: smoke
cutoff_len: 128
max_samples: 4
preprocessing_num_workers: 1
dataloader_num_workers: 0
output_dir: /workspace/training_artifacts/run9901/checkpoints
logging_dir: /workspace/training_artifacts/run9901/checkpoints/logs
logging_steps: 1
plot_loss: true
save_strategy: steps
save_steps: 1
overwrite_output_dir: false
report_to: wandb
run_name: factory_cloud_runner_smoke
per_device_train_batch_size: 1
gradient_accumulation_steps: 1
learning_rate: 0.0001
max_steps: 1
bf16: true
'@ | Set-Content -Encoding utf8 (Join-Path $runDir "cli_config.yml")

    @'
{
  "smoke": {
    "file_name": "smoke.json",
    "columns": {
      "prompt": "instruction",
      "query": "input",
      "response": "output"
    }
  }
}
'@ | Set-Content -Encoding utf8 (Join-Path $dataDir "dataset_info.json")

    @'
[
  {"instruction":"Return the word blue.","input":"","output":"blue"},
  {"instruction":"Return the word green.","input":"","output":"green"},
  {"instruction":"Add one and one.","input":"","output":"2"},
  {"instruction":"Say hello.","input":"","output":"hello"}
]
'@ | Set-Content -Encoding utf8 (Join-Path $dataDir "smoke.json")

    Invoke-Docker network create $network
    Invoke-Docker volume create $hfCache
    Invoke-Docker volume create $torchCache
    Invoke-Docker volume create $compiledCache
    Invoke-Docker run -d --name $server --network $network `
        --network-alias webdav `
        --mount "type=bind,source=$remote,target=/srv" `
        --mount "type=bind,source=$tlsDir,target=/tls,readonly" `
        --entrypoint rclone $Image `
        serve webdav /srv --addr :8443 --baseurl /remote.php/dav/files/smoke `
        --cert /tls/cert.pem --key /tls/key.pem --user smoke --pass smoke
    Start-Sleep -Seconds 2

    $runnerArgs = @(
        "run", "--rm", "--name", $runner, "--network", $network, "--gpus", "all",
        "-e", "RUN_IDS=run9901",
        "-e", "NEXTCLOUD_URL=https://webdav:8443/remote.php/dav/files/smoke",
        "-e", "NEXTCLOUD_USERNAME=smoke",
        "-e", "NEXTCLOUD_PASSWORD=smoke",
        "-e", "NEXTCLOUD_RUN_ROOT=/training_artifacts",
        "-e", "NEXTCLOUD_DATA_ROOT=/training_data",
        "-e", "NEXTCLOUD_MODEL_ROOT=/models",
        "-e", "WANDB_API_KEY=offline",
        "-e", "WANDB_PROJECT=FactoryCloudRunnerSmoke",
        "-e", "WANDB_MODE=offline",
        "-e", "WANDB_SILENT=true",
        "-e", "CUDA_VISIBLE_DEVICES=0",
        "-e", "RCLONE_NO_CHECK_CERTIFICATE=true",
        "-e", "RCLONE_WEBDAV_NEXTCLOUD_CHUNK_SIZE=0",
        "-v", "${hfCache}:/cache/huggingface",
        "-v", "${torchCache}:/cache/torch",
        "-v", "${compiledCache}:/cache/compiled",
        $Image
    )

    Invoke-Docker @runnerArgs
    $status = Get-Content (Join-Path $runDir "checkpoints\.runner\status.json") | ConvertFrom-Json
    if ($status.state -ne "succeeded" -or -not (Test-Path (Join-Path $runDir "checkpoints\checkpoint-1"))) {
        throw "First smoke run did not upload checkpoint-1 successfully"
    }

    $configPath = Join-Path $runDir "cli_config.yml"
    (Get-Content -Raw $configPath).Replace("max_steps: 1", "max_steps: 2") |
        Set-Content -Encoding utf8 $configPath
    Invoke-Docker @runnerArgs
    $status = Get-Content (Join-Path $runDir "checkpoints\.runner\status.json") | ConvertFrom-Json
    if ($status.state -ne "succeeded" -or -not (Test-Path (Join-Path $runDir "checkpoints\checkpoint-2"))) {
        throw "Resume smoke run did not upload checkpoint-2 successfully"
    }

    $baseConfig = Get-Content -Raw $configPath
    $failedRunDir = Join-Path $remote "training_artifacts\run9902"
    $continuedRunDir = Join-Path $remote "training_artifacts\run9903"
    New-Item -ItemType Directory -Force $failedRunDir, $continuedRunDir | Out-Null
    $baseConfig.Replace("run9901", "run9902").Replace(
        "output_dir: /workspace/training_artifacts/run9902/checkpoints",
        "output_dir: /workspace/training_artifacts/wrong/checkpoints"
    ) | Set-Content -Encoding utf8 (Join-Path $failedRunDir "cli_config.yml")
    $baseConfig.Replace("run9901", "run9903").Replace("max_steps: 2", "max_steps: 1") |
        Set-Content -Encoding utf8 (Join-Path $continuedRunDir "cli_config.yml")
    Invoke-Docker kill --signal SIGHUP $server

    $batchArgs = @($runnerArgs)
    $batchArgs[[Array]::IndexOf($batchArgs, "RUN_IDS=run9901")] = "RUN_IDS=run9902,run9903"
    & docker @batchArgs
    if ($LASTEXITCODE -ne 1) {
        throw "Two-run batch should exit 1 when its first run fails"
    }
    $failedStatus = Get-Content (Join-Path $failedRunDir "checkpoints\.runner\status.json") | ConvertFrom-Json
    $continuedStatus = Get-Content (Join-Path $continuedRunDir "checkpoints\.runner\status.json") | ConvertFrom-Json
    if ($failedStatus.state -ne "failed" -or $continuedStatus.state -ne "succeeded") {
        throw "Two-run batch did not continue after the expected first-run failure"
    }

    $terminatedRunDir = Join-Path $remote "training_artifacts\run9904"
    New-Item -ItemType Directory -Force $terminatedRunDir | Out-Null
    $baseConfig.Replace("run9901", "run9904").Replace("max_steps: 2", "max_steps: 1000") |
        Set-Content -Encoding utf8 (Join-Path $terminatedRunDir "cli_config.yml")
    Invoke-Docker kill --signal SIGHUP $server
    $signalArgs = @("run", "-d") + @($runnerArgs | Select-Object -Skip 2)
    $signalArgs[[Array]::IndexOf($signalArgs, "RUN_IDS=run9901")] = "RUN_IDS=run9904"
    Invoke-Docker @signalArgs

    $trainingStarted = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        $logs = (& docker logs $runner 2>&1 | Out-String)
        if ($logs -match "Total steps = 1,000|Total steps = 1000|0%\|") {
            $trainingStarted = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $trainingStarted) {
        throw "SIGTERM smoke run did not reach active training"
    }
    Invoke-Docker stop --timeout 180 $runner
    $terminatedStatus = Get-Content (Join-Path $terminatedRunDir "checkpoints\.runner\status.json") |
        ConvertFrom-Json
    if ($terminatedStatus.state -ne "terminated") {
        throw "SIGTERM smoke run did not upload a terminated status"
    }

    Write-Host "Container smoke, resume, batch continuation, and SIGTERM passed: $runDir"
}
finally {
    & docker rm -f $runner $server 2>$null | Out-Null
    & docker network rm $network 2>$null | Out-Null
    & docker volume rm $hfCache $torchCache $compiledCache 2>$null | Out-Null
    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $root)) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}

# FactoryCloudRunner

FactoryCloudRunner is a sealed, PID-1 Docker runner around a separately supplied LlamaFactory working tree. It downloads cloud-style runs and their inputs from Nextcloud, executes them in order, uploads checkpoints and diagnostics, then exits.

It does not start SSH, Jupyter, LlamaBoard, an idle shell, or any RunPod API integration.

## Image build

The local build script records the exact LlamaFactory commit and dirty state:

```powershell
.\scripts\build-local.ps1
```

The image uses a pinned Python 3.12 slim base plus the official CUDA 13 PyTorch wheels. Torch and its CUDA libraries therefore exist only once. The base digest, PyTorch index versions, FA2 wheel URL, and FA2 wheel SHA-256 are pinned. Source compilation is not used.

Dirty LlamaFactory trees are allowed for local images. A production build refuses them:

```powershell
.\scripts\build-local.ps1 -Production -Tag registry.example/factory-cloud-runner:revision
```

Inspect the installed engine metadata without starting a job:

```powershell
docker run --rm factory-cloud-runner:local --build-info
```

The image is pinned to PyTorch 2.9.0/CUDA 13.0, Transformers 5.5.0, Unsloth 2026.5.2, FlashAttention 2.8.3, Liger 0.8.0, bitsandbytes 0.49.2, DeepSpeed 0.18.4, W&B 0.27.0, and rclone 1.74.3. The build imports both `flash_attn` and its CUDA extension and fails if FA2 is unavailable.

Docker Engine defaults to a small number of concurrent layer downloads. For faster future pulls, merge this into Docker Desktop **Settings → Docker Engine** and restart Docker Desktop:

```json
{
  "max-concurrent-downloads": 10
}
```

Keep existing Docker Engine keys when adding it. Higher values can reduce performance if storage or antivirus scanning is the bottleneck.

## Nextcloud layout

`NEXTCLOUD_URL` must be the full WebDAV endpoint, normally:

```text
https://cloud.example.com/remote.php/dav/files/username
```

The three remote roots are independent:

```text
NEXTCLOUD_RUN_ROOT=/remote/path/training_artifacts
NEXTCLOUD_DATA_ROOT=/remote/path/training_data
NEXTCLOUD_MODEL_ROOT=/AI Models/LLM
```

For `run0073`, the runner downloads `NEXTCLOUD_RUN_ROOT/run0073`, requires exactly one `cli_config.yml`, and requires:

```yaml
model_name_or_path: some-public-huggingface/model
dataset_dir: /workspace/data/SkyrimCYOA_SFT/llamafactory
output_dir: /workspace/training_artifacts/run0073/checkpoints
logging_dir: /workspace/training_artifacts/run0073/checkpoints/logs
report_to: wandb
run_name: run0073_description
```

A private model uses:

```yaml
model_name_or_path: /workspace/models/private-model-name
```

Dataset and private-model paths are mapped relative to their respective Nextcloud roots. Public Hugging Face IDs are left unchanged for LlamaFactory to download.

After every success, failure, or interrupted training process, the runner writes and uploads:

```text
run0073/checkpoints/.runner/status.json
run0073/checkpoints/.runner/runner.log
```

All other LlamaFactory checkpoint contents are uploaded unchanged. Existing remote checkpoints are downloaded first, so LlamaFactory's normal last-checkpoint detection resumes the run.

## Local execution

Create the ignored runtime environment file:

```powershell
Copy-Item .env.example .env.local
notepad .env.local
```

Then run the sealed image with no repository bind mount:

```powershell
.\scripts\run-local.ps1
```

All GPUs are exposed by default. Set `CUDA_VISIBLE_DEVICES=0` in `.env.local` to select one. Hugging Face, Torch, Triton, TorchInductor, and Unsloth caches persist in named Docker volumes.

Exercise the future deletion hook without calling RunPod:

```powershell
.\scripts\run-local.ps1 -MockRunPodDelete
```

The runner processes every `RUN_IDS` entry even if an earlier training run fails. It exits zero only when every run and every checkpoint upload succeeds.

On SIGTERM or SIGINT, the runner forwards the signal to the LlamaFactory process group, waits up to 120 seconds, kills it if necessary, uploads partial checkpoints, and exits nonzero.

## Tests

Run the local unit checks:

```powershell
python -m unittest discover -s tests -v
```

Before adding any RunPod API call, perform the real pipeline test with a new cloud-only run number and the actual 7B recipe, changing only:

```yaml
max_steps: 1
save_strategy: steps
save_steps: 1
```

Verify:

1. `--build-info` reports the intended LlamaFactory commit and dirty flag.
2. The remote run initially contains only `cli_config.yml`.
3. Dataset retrieval and public-HF or private-model retrieval succeed.
4. W&B receives the run.
5. One training step writes and uploads the complete `checkpoints/` tree.
6. The container exits without interaction.
7. SIGTERM produces a terminated status and uploads partial diagnostics.
8. In a two-run batch, a deliberately invalid first run does not prevent the second.
9. Relaunching the one-step run resumes from its downloaded checkpoint.

Actual RunPod calls remain absent until the pipeline passes.

## Current real run0073 setup

The synchronized Windows paths map to these WebDAV roots:

```text
N:\AI Models\TwineLLMFinetune\runs
  -> NEXTCLOUD_RUN_ROOT=/AI Models/TwineLLMFinetune/runs

N:\AI Models\TwineLLMFinetune\training_data
  -> NEXTCLOUD_DATA_ROOT=/AI Models/TwineLLMFinetune/training_data
```

`run0073/cli_config.yml` is configured with:

```yaml
model_name_or_path: Mawdistical/Kuwutu-7B
dataset_dir: /workspace/data/SkyrimCYOA_SFT/llamafactory
output_dir: /workspace/training_artifacts/run0073/checkpoints
logging_dir: /workspace/training_artifacts/run0073/checkpoints/logs
max_steps: 1
save_strategy: steps
save_steps: 1
```

Therefore the dataset must exist remotely, and in the synchronized Windows view, at:

```text
N:\AI Models\TwineLLMFinetune\training_data\SkyrimCYOA_SFT\llamafactory
```

The local `training_data` directory was empty when this configuration was prepared. Populate that directory before launching the real test.

An ignored `.env.local` is prepared with the run ID, roots, W&B project, GPU selection, and existing W&B/Hugging Face tokens. Open it once and replace only:

```text
NEXTCLOUD_URL=https://your-host/remote.php/dav/files/KeinNiemand
NEXTCLOUD_PASSWORD=your-nextcloud-app-password
```

Use the HTTPS WebDAV endpoint, not the Windows SMB path shown by `N:`. Then launch the sealed image:

```powershell
.\scripts\run-local.ps1
```

No repository directory is mounted into the container. Model, dataset, checkpoint, Triton, and Hugging Face downloads can make the first launch slow; later launches reuse named cache volumes.

Verify completion at:

```text
N:\AI Models\TwineLLMFinetune\runs\run0073\checkpoints\.runner\status.json
```

Rerunning the same command downloads the uploaded checkpoints and resumes automatically. After the one-step test passes, remove `max_steps: 1` from `run0073/cli_config.yml` and restore the desired checkpoint interval, such as `save_steps: 30`, to run the complete two-epoch configuration.

The reproducible small-model sealed-container test is:

```powershell
.\tests\container-smoke.ps1
```

It uses a temporary HTTPS WebDAV server, performs one real FA2/Unsloth/Liger/LoRA+ training step, uploads the checkpoint, relaunches, and resumes to step two.

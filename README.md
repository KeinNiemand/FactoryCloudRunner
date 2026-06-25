# FactoryCloudRunner

FactoryCloudRunner is a sealed, PID-1 Docker runner around a separately supplied LlamaFactory working tree. It downloads cloud-style runs and their inputs from Nextcloud, executes them in order, uploads checkpoints and diagnostics, then exits.

It does not start SSH, Jupyter, LlamaBoard, or an idle shell. On RunPod it can stop or terminate its own Pod after the final upload.

## Image build

The local build script records the exact LlamaFactory commit and dirty state:

```powershell
.\scripts\build-local.ps1
```

The image uses a pinned Python 3.12 slim base plus the official CUDA 13 PyTorch wheels. Torch and its CUDA libraries therefore exist only once. The base digest, PyTorch index versions, FA2 wheel URL, and FA2 wheel SHA-256 are pinned. Source compilation is not used.

Dirty LlamaFactory source trees are allowed for local images. A production build refuses them; untracked `.codex/` tool state is ignored because it is excluded from the build context:

```powershell
.\scripts\build-local.ps1 -Production -Tag registry.example/factory-cloud-runner:revision
```

Production images are `linux/amd64` only. Push one directly with:

```powershell
.\scripts\build-local.ps1 `
  -Production `
  -Push `
  -PackageIsPublic `
  -Tag ghcr.io/keinniemand/factory-cloud-runner:v0.1.0
```

Bootstrap the tiny GHCR placeholder and make that package public before uploading the full image. Builds and pushes remain local so the existing multi-gigabyte Docker cache is reused. See [docs/runpod.md](docs/runpod.md) for registry and RunPod setup.

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
NEXTCLOUD_MODEL_ROOT=/remote/path/models
```

For example, `run0123` downloads from `NEXTCLOUD_RUN_ROOT/run0123`, requires exactly one `cli_config.yml`, and uses container-native paths:

```yaml
model_name_or_path: some-public-huggingface/model
dataset_dir: /workspace/data/my_dataset/llamafactory
output_dir: /workspace/training_artifacts/run0123/checkpoints
logging_dir: /workspace/training_artifacts/run0123/checkpoints/logs
report_to: wandb
run_name: run0123_description
```

A private model uses:

```yaml
model_name_or_path: /workspace/models/private-model-name
```

Dataset and private-model paths are mapped relative to their respective Nextcloud roots. Public Hugging Face IDs are left unchanged for LlamaFactory to download.

After every success, failure, or interrupted training process, the runner writes and uploads:

```text
run0123/checkpoints/.runner/status.json
run0123/checkpoints/.runner/runner.log
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

Single-machine tuning (`FORCE_TORCHRUN`, `USE_RAY`, `UNSLOTH_CE_LOSS_TARGET_GB`, and `PYTORCH_ALLOC_CONF`) lives in `.env.local`/Compose rather than the image. RunPod therefore starts without those local defaults and can select its own multi-GPU settings.

Mock the RunPod stop/delete requests without making a network call:

```powershell
python -m unittest tests.test_runpod -v
```

The runner processes every `RUN_IDS` entry even if an earlier training run fails. It exits zero only when every run and every checkpoint upload succeeds.

On SIGTERM or SIGINT, the runner forwards the signal to the LlamaFactory process group, waits up to 120 seconds, kills it if necessary, uploads partial checkpoints, and exits nonzero.

When `RUNPOD_POD_ID` is present, the runner defaults to calling RunPod's stop endpoint after all uploads. Set `RUNPOD_SHUTDOWN_ACTION=terminate` for disposable Pods or `none` to disable the API call. Termination is used only after complete success; failures are stopped so the Pod disk is preserved. RunPod credentials are removed from inherited child-process environments before LlamaFactory or rclone starts.

## Tests

Run the local unit checks:

```powershell
python -m unittest discover -s tests -v
```

The local pipeline was proven before adding the bounded RunPod shutdown call. For each new image, perform a real pipeline test with a new cloud-only run number and the actual 7B recipe, changing only:

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

The RunPod API client is unit-tested locally; the next deployment test should use `RUNPOD_SHUTDOWN_ACTION=stop` before enabling Pod deletion.

## Preparing a real local test

A synchronized Windows folder may help you prepare files, but configure the runner with paths relative to the Nextcloud WebDAV account:

```text
X:\Nextcloud\training\runs
  -> NEXTCLOUD_RUN_ROOT=/training/runs

X:\Nextcloud\training\data
  -> NEXTCLOUD_DATA_ROOT=/training/data
```

The drive letter and local synchronization root are not part of the WebDAV path. Put the run YAML under the synchronized `runs\run0123` directory and its referenced dataset under `data`.

For a smoke run, keep the real model and training recipe but temporarily add:

```yaml
max_steps: 1
save_strategy: steps
save_steps: 1
```

Copy `.env.example` to the ignored `.env.local`, fill in the WebDAV endpoint and runtime credentials, then launch:

```powershell
.\scripts\run-local.ps1
```

No repository directory is mounted into the container. First-run model and kernel downloads may be slow; later runs reuse named cache volumes. Completion is recorded remotely under `run0123/checkpoints/.runner/status.json`. Relaunching the same run downloads its checkpoints and relies on LlamaFactory's normal resume behavior.

The reproducible small-model sealed-container test is:

```powershell
.\tests\container-smoke.ps1
```

It uses a temporary HTTPS WebDAV server, performs one real FA2/Unsloth/Liger/LoRA+ training step, uploads the checkpoint, relaunches, and resumes to step two.

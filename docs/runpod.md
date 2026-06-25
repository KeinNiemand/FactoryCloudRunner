# RunPod deployment

FactoryCloudRunner is a `linux/amd64` image. RunPod Pods do not support ARM images, and the pinned FlashAttention wheel is also x86_64.

## 1. Bootstrap a public package

GitHub creates a personal-account package as private on its first push. Do not upload the multi-gigabyte CUDA image in that state.

Sign in to GHCR, then publish the effectively empty bootstrap image:

```powershell
docker login ghcr.io -u KeinNiemand
.\scripts\bootstrap-ghcr.ps1
```

Open the package settings link printed by the script, choose **Change visibility → Public**, and confirm. GitHub does not expose package visibility through the Packages REST API, so this one-time visibility change is manual. A public package cannot later be made private.

The bootstrap image is tiny, so it stays far below the private package quota. The local publisher refuses to upload the full image until you explicitly confirm that the package is public.

## 2. Publish the image

The shortest path is a local production push:

```powershell
.\scripts\build-local.ps1 `
  -Production `
  -Push `
  -PackageIsPublic `
  -Tag ghcr.io/keinniemand/factory-cloud-runner:v0.1.0
```

Use a GitHub token with `write:packages` for `docker login`. A production push requires clean, committed FactoryCloudRunner and LlamaFactory working trees. The image includes an `org.opencontainers.image.source` label linking it to the public FactoryCloudRunner repository.

The image is built locally because this machine already has the expensive Torch, CUDA, Unsloth, and FlashAttention layers cached. A hosted GitHub runner would download and rebuild that stack from scratch.

## 3. Store RunPod secrets

Create these RunPod secrets:

```text
nextcloud_username
nextcloud_password
wandb_api_key
hf_token
```

`hf_token` is optional for a public model, except where Hugging Face requires authentication or license acceptance.

## 4. Create the Pod template

Create a RunPod Pod template with:

```text
Container image: ghcr.io/keinniemand/factory-cloud-runner:v0.1.0
Container disk: 80 GB initially
Container start command: leave empty
Exposed ports: none
Volume mounts: none required
```

The runner is the image entrypoint and must remain PID 1. Do not replace the command with a shell.

Add these environment variables:

```text
RUN_IDS=run0123

NEXTCLOUD_URL=https://your-host/remote.php/dav/files/username
NEXTCLOUD_USERNAME={{ RUNPOD_SECRET_nextcloud_username }}
NEXTCLOUD_PASSWORD={{ RUNPOD_SECRET_nextcloud_password }}
NEXTCLOUD_RUN_ROOT=/training/runs
NEXTCLOUD_DATA_ROOT=/training/data
NEXTCLOUD_MODEL_ROOT=/models

WANDB_API_KEY={{ RUNPOD_SECRET_wandb_api_key }}
WANDB_PROJECT=my-training-project
WANDB_ENTITY=
HF_TOKEN={{ RUNPOD_SECRET_hf_token }}

RUNPOD_SHUTDOWN_ACTION=stop
```

RunPod injects `RUNPOD_POD_ID` and a Pod-scoped `RUNPOD_API_KEY`; do not add either manually. The runner removes all `RUNPOD_*` values before starting LlamaFactory.

Use `stop` while validating the deployment. It preserves the stopped Pod and its container disk. Once the workflow is proven disposable, use:

```text
RUNPOD_SHUTDOWN_ACTION=terminate
```

That deletes the Pod only after every requested run and checkpoint upload succeeds. On any startup, training, or upload failure, the runner stops the Pod instead so its container disk remains recoverable.

## 5. Start and verify

Deploy a GPU Pod from the template. No SSH or web port is needed. The container:

1. downloads the run, dataset, and optional private model;
2. trains all IDs in `RUN_IDS`;
3. uploads checkpoints and `.runner` diagnostics;
4. asks RunPod to stop or terminate the Pod;
5. exits.

Verify the final state at:

```text
NEXTCLOUD_RUN_ROOT/run0123/checkpoints/.runner/status.json
```

Use a new cloud-only run ID for a full training run. Remove the smoke-test `max_steps: 1` and restore the intended save interval before starting it.

RunPod image requirements and Pod environment behavior are documented at:

- https://docs.runpod.io/pods/templates/container-image-requirements
- https://docs.runpod.io/pods/templates/environment-variables
- https://docs.runpod.io/pods/templates/secrets

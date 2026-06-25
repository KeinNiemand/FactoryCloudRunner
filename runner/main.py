from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Callable

from .config import Settings, load_run_config
from .nextcloud import RcloneClient
from .runpod import request_shutdown
from .status import utc_now, write_status
from .training import ShutdownController, run_training


LOGGER = logging.getLogger("factory-cloud-runner")
TrainFunction = Callable[[Path, dict[str, str], ShutdownController, logging.Logger], int]


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def _run_logger(run_id: str, log_path: Path) -> tuple[logging.LoggerAdapter, logging.Handler]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    return logging.LoggerAdapter(LOGGER, {"run_id": run_id}), handler


def _training_environment(settings: Settings, checkpoints: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if (
            name.startswith("NEXTCLOUD_")
            or name.startswith("RUNNER_")
            or name.startswith("RUNPOD_")
            or name == "RUN_IDS"
        ):
            environment.pop(name)
    environment.update(
        {
            "WANDB_API_KEY": settings.wandb_api_key,
            "WANDB_PROJECT": settings.wandb_project,
            "WANDB_DIR": "/cache/wandb",
            "LLAMAFACTORY_SEPARATE_EVAL": "0",
            "HF_HOME": "/cache/huggingface",
            "HF_HUB_CACHE": "/cache/huggingface/hub",
            "HF_DATASETS_CACHE": "/cache/huggingface/datasets",
            "TORCH_HOME": "/cache/torch",
            "TRITON_CACHE_DIR": "/cache/compiled/triton",
            "TORCHINDUCTOR_CACHE_DIR": "/cache/compiled/torchinductor",
            "UNSLOTH_COMPILE_CACHE": "/cache/compiled/unsloth",
        }
    )
    if settings.wandb_entity:
        environment["WANDB_ENTITY"] = settings.wandb_entity
    else:
        environment.pop("WANDB_ENTITY", None)
    if settings.hf_token:
        environment["HF_TOKEN"] = settings.hf_token
        environment["HUGGING_FACE_HUB_TOKEN"] = settings.hf_token
    return environment


def _remove_runtime_credentials() -> None:
    for name in tuple(os.environ):
        if (
            name.startswith("NEXTCLOUD_")
            or name.startswith("RUNPOD_")
            or name == "WANDB_API_KEY"
            or name in {"HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"}
        ):
            os.environ.pop(name)


def _write_status_safely(
    path: Path,
    *,
    run_id: str,
    state: str,
    started_at: str,
    exit_code: int | None,
    error: str | None,
) -> bool:
    try:
        write_status(
            path,
            run_id=run_id,
            state=state,
            started_at=started_at,
            exit_code=exit_code,
            error=error,
        )
        return True
    except Exception:
        LOGGER.exception("%s: status write failed", run_id)
        return False


def process_run(
    settings: Settings,
    client: RcloneClient,
    shutdown: ShutdownController,
    run_id: str,
    train: TrainFunction = run_training,
) -> bool:
    started_at = utc_now()
    run_dir = settings.workspace_root / run_id
    checkpoints = run_dir / "checkpoints"
    runner_dir = checkpoints / ".runner"
    run_dir.mkdir(parents=True, exist_ok=True)
    logger: logging.LoggerAdapter | None = None
    handler: logging.Handler | None = None
    state = "failed"
    exit_code: int | None = None
    error: str | None = None

    try:
        LOGGER.info("%s: downloading remote run directory", run_id)
        client.download_run(run_id, run_dir)
        logger, handler = _run_logger(run_id, runner_dir / "runner.log")
        logger.info("processing %s", run_id)

        run = load_run_config(run_dir, run_id)
        logger.info("downloading dataset %s", run.dataset_relative)
        client.download_dataset(run.dataset_relative)
        if run.model_relative:
            logger.info("downloading private model %s", run.model_relative)
            client.download_model(run.model_relative)
        else:
            logger.info("using Hugging Face model ID %s", run.values["model_name_or_path"])

        if shutdown.requested.is_set():
            raise InterruptedError("shutdown requested before training started")

        exit_code = train(run.path, _training_environment(settings, checkpoints), shutdown, logger.logger)
        if shutdown.requested.is_set():
            state = "terminated"
            error = f"received signal {shutdown.signal_number}"
        elif exit_code == 0:
            state = "succeeded"
        else:
            error = f"llamafactory-cli exited with code {exit_code}"
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"
        state = "terminated" if shutdown.requested.is_set() else "failed"
        (logger or LOGGER).exception("%s failed", run_id)
    finally:
        status_path = runner_dir / "status.json"
        if not _write_status_safely(
            status_path,
            run_id=run_id,
            state=state,
            started_at=started_at,
            exit_code=exit_code,
            error=error,
        ):
            state = "failed"
            error = f"{error + '; ' if error else ''}status write failed"
        try:
            LOGGER.info("%s: uploading checkpoints", run_id)
            client.upload_checkpoints(run_id, checkpoints)
        except Exception as upload_exception:
            LOGGER.exception("%s: checkpoint upload failed", run_id)
            state = "failed"
            error = f"{error + '; ' if error else ''}upload failed: {upload_exception}"
            _write_status_safely(
                status_path,
                run_id=run_id,
                state=state,
                started_at=started_at,
                exit_code=exit_code,
                error=error,
            )
            try:
                client.upload_runner_metadata(run_id, runner_dir)
            except Exception:
                LOGGER.exception("%s: runner metadata upload failed", run_id)
        if shutdown.requested.is_set() and state == "succeeded":
            state = "terminated"
            error = f"received signal {shutdown.signal_number}"
            if _write_status_safely(
                status_path,
                run_id=run_id,
                state=state,
                started_at=started_at,
                exit_code=exit_code,
                error=error,
            ):
                try:
                    client.upload_runner_metadata(run_id, runner_dir)
                except Exception:
                    LOGGER.exception("%s: terminated status upload failed", run_id)
        if handler:
            LOGGER.removeHandler(handler)
            handler.close()

    return state == "succeeded"


def run_batch(
    settings: Settings,
    client: RcloneClient,
    shutdown: ShutdownController,
    train: TrainFunction = run_training,
) -> int:
    succeeded = []
    for run_id in settings.run_ids:
        if shutdown.requested.is_set():
            break
        succeeded.append(process_run(settings, client, shutdown, run_id, train))
    return 0 if not shutdown.requested.is_set() and len(succeeded) == len(settings.run_ids) and all(succeeded) else 1


def build_info() -> dict[str, str]:
    try:
        from importlib.metadata import version

        package_version = version("llamafactory")
    except Exception:
        package_version = "unavailable"
    return {
        "llamafactory_version": package_version,
        "llamafactory_commit": os.getenv("LLAMAFACTORY_COMMIT", "unknown"),
        "llamafactory_dirty": os.getenv("LLAMAFACTORY_DIRTY", "unknown"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-info", action="store_true")
    arguments = parser.parse_args()
    if arguments.build_info:
        print(json.dumps(build_info(), indent=2, sort_keys=True))
        return 0

    _configure_logging()
    result = 1
    runpod_environment = {
        name: value
        for name in ("RUNPOD_SHUTDOWN_ACTION", "RUNPOD_POD_ID", "RUNPOD_API_KEY")
        if (value := os.environ.get(name)) is not None
    }
    try:
        settings = Settings.from_env()
        _remove_runtime_credentials()
        shutdown = ShutdownController(settings.shutdown_timeout_seconds)
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signal_number, lambda received, _frame: shutdown.request(received))
        LOGGER.info("LlamaFactory build: %s", json.dumps(build_info(), sort_keys=True))
        with RcloneClient(settings, shutdown) as client:
            result = run_batch(settings, client, shutdown)
    except Exception:
        LOGGER.exception("runner startup failed")
    finally:
        _remove_runtime_credentials()
        try:
            request_shutdown(runpod_environment, allow_terminate=result == 0, logger=LOGGER)
        except Exception:
            LOGGER.exception("RunPod shutdown request failed")
            result = 1
    return result


if __name__ == "__main__":
    sys.exit(main())

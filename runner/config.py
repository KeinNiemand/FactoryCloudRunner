from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from urllib.parse import urlparse

import yaml


RUN_ID_PATTERN = re.compile(r"run\d{4}")
WORKSPACE_ROOT = Path("/workspace/training_artifacts")
DATA_ROOT = PurePosixPath("/workspace/data")
MODEL_ROOT = PurePosixPath("/workspace/models")
HF_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?")


def parse_run_ids(value: str) -> tuple[str, ...]:
    run_ids = tuple(part.strip() for part in value.split(",") if part.strip())
    if not run_ids:
        raise ValueError("RUN_IDS must contain at least one run ID")
    invalid = [run_id for run_id in run_ids if not RUN_ID_PATTERN.fullmatch(run_id)]
    if invalid:
        raise ValueError(f"Invalid run ID(s): {', '.join(invalid)}")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("RUN_IDS must not contain duplicates")
    return run_ids


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must not contain newlines")
    return value


def _https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("NEXTCLOUD_URL must be an HTTPS URL without embedded credentials")
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    run_ids: tuple[str, ...]
    nextcloud_url: str
    nextcloud_username: str
    nextcloud_password: str
    nextcloud_run_root: str
    nextcloud_data_root: str
    nextcloud_model_root: str
    wandb_api_key: str
    wandb_project: str
    wandb_entity: str | None
    hf_token: str | None
    workspace_root: Path = WORKSPACE_ROOT
    shutdown_timeout_seconds: float = 120.0
    upload_timeout_seconds: float = 600.0
    metadata_upload_timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        return cls(
            run_ids=parse_run_ids(_required(env, "RUN_IDS")),
            nextcloud_url=_https_url(_required(env, "NEXTCLOUD_URL")),
            nextcloud_username=_required(env, "NEXTCLOUD_USERNAME"),
            nextcloud_password=_required(env, "NEXTCLOUD_PASSWORD"),
            nextcloud_run_root=_required(env, "NEXTCLOUD_RUN_ROOT"),
            nextcloud_data_root=_required(env, "NEXTCLOUD_DATA_ROOT"),
            nextcloud_model_root=_required(env, "NEXTCLOUD_MODEL_ROOT"),
            wandb_api_key=_required(env, "WANDB_API_KEY"),
            wandb_project=_required(env, "WANDB_PROJECT"),
            wandb_entity=env.get("WANDB_ENTITY", "").strip() or None,
            hf_token=env.get("HF_TOKEN", "").strip() or None,
        )


@dataclass(frozen=True)
class RunConfig:
    path: Path
    values: dict
    dataset_relative: PurePosixPath
    model_relative: PurePosixPath | None


def _relative_container_path(value: object, root: PurePosixPath, name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise ValueError(f"{name} must not contain '..'")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{name} must be under {root}") from error
    if not relative.parts:
        raise ValueError(f"{name} must select a directory below {root}")
    return relative


def load_run_config(run_dir: Path, run_id: str) -> RunConfig:
    configs = list(run_dir.rglob("cli_config.yml"))
    if len(configs) != 1:
        raise ValueError(f"{run_id} must contain exactly one cli_config.yml; found {len(configs)}")

    with configs[0].open("r", encoding="utf-8") as handle:
        values = yaml.safe_load(handle)
    if not isinstance(values, dict):
        raise ValueError("cli_config.yml must contain a YAML mapping")

    expected_output = f"/workspace/training_artifacts/{run_id}/checkpoints"
    if values.get("output_dir") != expected_output:
        raise ValueError(f"output_dir must equal {expected_output}")

    dataset_relative = _relative_container_path(values.get("dataset_dir"), DATA_ROOT, "dataset_dir")
    model = values.get("model_name_or_path")
    if not isinstance(model, str) or not model:
        raise ValueError("model_name_or_path must be a non-empty string")
    if model.startswith(f"{MODEL_ROOT}/"):
        model_relative = _relative_container_path(model, MODEL_ROOT, "model_name_or_path")
    else:
        if not HF_MODEL_PATTERN.fullmatch(model):
            raise ValueError("model_name_or_path must be a Hugging Face ID or a path under /workspace/models")
        model_relative = None

    logging_dir = values.get("logging_dir")
    if logging_dir is not None:
        _relative_container_path(
            logging_dir,
            PurePosixPath(expected_output),
            "logging_dir",
        )
    return RunConfig(configs[0], values, dataset_relative, model_relative)

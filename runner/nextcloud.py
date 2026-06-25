from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

from .config import Settings
from .training import ShutdownController


def remote_path(root: str, *parts: object) -> str:
    path = PurePosixPath(root)
    for part in parts:
        path /= str(part)
    if ".." in path.parts:
        raise ValueError("Nextcloud paths must not contain '..'")
    return f"nextcloud:{str(path).lstrip('/')}"


class RcloneClient:
    def __init__(self, settings: Settings, shutdown: ShutdownController | None = None):
        self.settings = settings
        self.shutdown = shutdown
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self.config_path: Path | None = None

    def __enter__(self) -> RcloneClient:
        obscured = subprocess.run(
            ["rclone", "obscure", "-"],
            input=f"{self.settings.nextcloud_password}\n",
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="factory-rclone-")
        self.config_path = Path(self._temporary_directory.name) / "rclone.conf"
        self.config_path.write_text(
            "[nextcloud]\n"
            "type = webdav\n"
            f"url = {self.settings.nextcloud_url}\n"
            "vendor = nextcloud\n"
            f"user = {self.settings.nextcloud_username}\n"
            f"pass = {obscured}\n",
            encoding="utf-8",
        )
        os.chmod(self.config_path, 0o600)
        return self

    def __exit__(self, *_: object) -> None:
        if self._temporary_directory:
            self._temporary_directory.cleanup()

    def copy(
        self,
        source: str | Path,
        destination: str | Path,
        *,
        interruptible: bool = True,
        timeout_seconds: float | None = None,
    ) -> None:
        if not self.config_path:
            raise RuntimeError("RcloneClient must be used as a context manager")
        command = [
            "rclone",
            "copy",
            str(source),
            str(destination),
            "--config",
            str(self.config_path),
            "--create-empty-src-dirs",
            "--retries",
            "3",
            "--low-level-retries",
            "10",
            "--stats",
            "30s",
            "--stats-one-line",
        ]
        if not interruptible or not self.shutdown:
            subprocess.run(
                command,
                check=True,
                timeout=timeout_seconds,
            )
            return

        process = subprocess.Popen(command, start_new_session=True)
        self.shutdown.attach(process)
        try:
            while process.poll() is None:
                self.shutdown.enforce_timeout()
                time.sleep(0.2)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        finally:
            self.shutdown.detach()

    def download_run(self, run_id: str, destination: Path) -> None:
        self.copy(remote_path(self.settings.nextcloud_run_root, run_id), destination)

    def download_dataset(self, relative: PurePosixPath) -> None:
        self.copy(
            remote_path(self.settings.nextcloud_data_root, relative),
            Path("/workspace/data").joinpath(*relative.parts),
        )

    def download_model(self, relative: PurePosixPath) -> None:
        self.copy(
            remote_path(self.settings.nextcloud_model_root, relative),
            Path("/workspace/models").joinpath(*relative.parts),
        )

    def upload_checkpoints(self, run_id: str, source: Path) -> None:
        self.copy(
            source,
            remote_path(self.settings.nextcloud_run_root, run_id, "checkpoints"),
            interruptible=False,
            timeout_seconds=self.settings.upload_timeout_seconds,
        )

    def upload_runner_metadata(self, run_id: str, source: Path) -> None:
        self.copy(
            source,
            remote_path(self.settings.nextcloud_run_root, run_id, "checkpoints", ".runner"),
            interruptible=False,
            timeout_seconds=self.settings.metadata_upload_timeout_seconds,
        )

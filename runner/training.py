from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from contextlib import suppress
from pathlib import Path


class ShutdownController:
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        self.requested = threading.Event()
        self.signal_number: int | None = None
        self._deadline: float | None = None
        self._process: subprocess.Popen[str] | None = None

    def attach(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        if self.requested.is_set():
            self._forward(self.signal_number or signal.SIGTERM)

    def detach(self) -> None:
        self._process = None

    def request(self, signal_number: int) -> None:
        if self.requested.is_set():
            return
        self.signal_number = signal_number
        self._deadline = time.monotonic() + self.timeout_seconds
        self.requested.set()
        self._forward(signal_number)

    def _forward(self, signal_number: int) -> None:
        process = self._process
        if not process or process.poll() is not None:
            return
        with suppress(ProcessLookupError):
            if os.name == "posix":
                os.killpg(process.pid, signal_number)
            else:
                process.send_signal(signal_number)

    def enforce_timeout(self) -> None:
        process = self._process
        if (
            process
            and process.poll() is None
            and self._deadline is not None
            and time.monotonic() >= self._deadline
        ):
            with suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()


def _stream_output(process: subprocess.Popen[str], logger: logging.Logger) -> None:
    assert process.stdout
    for line in process.stdout:
        logger.info("train | %s", line.rstrip())


def run_training(
    config_path: Path,
    environment: dict[str, str],
    shutdown: ShutdownController,
    logger: logging.Logger,
) -> int:
    process = subprocess.Popen(
        ["llamafactory-cli", "train", str(config_path)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    shutdown.attach(process)
    output_thread = threading.Thread(target=_stream_output, args=(process, logger), daemon=True)
    output_thread.start()
    try:
        while process.poll() is None:
            shutdown.enforce_timeout()
            time.sleep(0.2)
        output_thread.join(timeout=5)
        return process.returncode
    finally:
        shutdown.detach()

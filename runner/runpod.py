from __future__ import annotations

import logging
import json
import os
import time
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ShutdownOpener = Callable[..., object]
VALID_ACTIONS = {"none", "stop", "terminate"}


def shutdown_action(environment: Mapping[str, str]) -> str:
    configured = environment.get("RUNPOD_SHUTDOWN_ACTION", "").strip().lower()
    action = configured or ("stop" if environment.get("RUNPOD_POD_ID") else "none")
    if action not in VALID_ACTIONS:
        raise ValueError("RUNPOD_SHUTDOWN_ACTION must be one of: none, stop, terminate")
    return action


def request_shutdown(
    environment: Mapping[str, str] | None = None,
    *,
    allow_terminate: bool = True,
    opener: ShutdownOpener = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    logger: logging.Logger | None = None,
) -> bool:
    environment = os.environ if environment is None else environment
    action = shutdown_action(environment)
    if action == "none":
        return False
    if action == "terminate" and not allow_terminate:
        action = "stop"
        if logger:
            logger.warning("Run failed; stopping Pod instead of terminating it so local data is preserved")

    pod_id = environment.get("RUNPOD_POD_ID", "").strip()
    api_key = environment.get("RUNPOD_API_KEY", "").strip()
    if not pod_id:
        raise ValueError(f"RUNPOD_POD_ID is required for RunPod {action}")
    if not api_key:
        raise ValueError(f"RUNPOD_API_KEY is required for RunPod {action}")

    field = "podStop" if action == "stop" else "podTerminate"
    output = " { id desiredStatus }" if action == "stop" else ""
    query = f"mutation($input: Pod{action.title()}Input!) {{ {field}(input: $input){output} }}"
    request = Request(
        f"https://api.runpod.io/graphql?{urlencode({'api_key': api_key})}",
        data=json.dumps({"query": query, "variables": {"input": {"podId": pod_id}}}).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "FactoryCloudRunner/0.1",
        },
    )

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with opener(request, timeout=20) as response:
                status = getattr(response, "status", 200)
                if 200 <= status < 300:
                    body = response.read()
                    payload = json.loads(body.decode("utf-8")) if body else {}
                    if payload.get("errors"):
                        raise RuntimeError(f"RunPod GraphQL returned errors: {payload['errors']}")
                    if logger:
                        logger.info("RunPod %s requested for pod %s", action, pod_id)
                    return True
                raise RuntimeError(f"RunPod API returned HTTP {status}")
        except HTTPError as exception:
            if exception.code == 404 or (action == "stop" and exception.code == 409):
                if logger:
                    logger.info("RunPod pod is already absent or stopped")
                return True
            if exception.code in {401, 403}:
                raise RuntimeError(f"RunPod {action} authorization failed: HTTP {exception.code}") from exception
            last_error = exception
            if attempt < 3:
                if logger:
                    logger.warning("RunPod %s attempt %d failed: %s", action, attempt, exception)
                sleep(float(attempt))
        except (URLError, TimeoutError, RuntimeError) as exception:
            last_error = exception
            if attempt < 3:
                if logger:
                    logger.warning("RunPod %s attempt %d failed: %s", action, attempt, exception)
                sleep(float(attempt))

    raise RuntimeError(f"RunPod {action} failed after 3 attempts: {last_error}")

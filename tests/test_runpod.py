import json
import unittest
from unittest import mock
from urllib.error import HTTPError

from runner.runpod import request_shutdown, shutdown_action


class FakeResponse:
    status = 200

    def __init__(self, body: bytes = b'{"data": {}}'):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class RunPodTests(unittest.TestCase):
    def test_local_default_does_nothing(self):
        self.assertEqual(shutdown_action({}), "none")
        self.assertFalse(request_shutdown({}, opener=lambda *_args, **_kwargs: None))

    def test_runpod_default_stops_pod(self):
        calls = []

        def open_request(request, timeout):
            calls.append((request, timeout))
            return FakeResponse()

        result = request_shutdown(
            {"RUNPOD_POD_ID": "pod 123", "RUNPOD_API_KEY": "secret"},
            opener=open_request,
        )

        self.assertTrue(result)
        request, timeout = calls[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.runpod.io/graphql?api_key=secret")
        self.assertEqual(request.method, "POST")
        self.assertIn("podStop", payload["query"])
        self.assertEqual(payload["variables"], {"input": {"podId": "pod 123"}})
        self.assertEqual(timeout, 20)

    def test_terminate_deletes_pod(self):
        calls = []

        def open_request(request, timeout):
            calls.append((request, timeout))
            return FakeResponse()

        request_shutdown(
            {
                "RUNPOD_SHUTDOWN_ACTION": "terminate",
                "RUNPOD_POD_ID": "pod123",
                "RUNPOD_API_KEY": "secret",
            },
            opener=open_request,
        )

        payload = json.loads(calls[0][0].data.decode("utf-8"))
        self.assertEqual(calls[0][0].full_url, "https://api.runpod.io/graphql?api_key=secret")
        self.assertEqual(calls[0][0].method, "POST")
        self.assertIn("podTerminate", payload["query"])

    def test_failed_run_stops_instead_of_terminating(self):
        calls = []

        def open_request(request, timeout):
            calls.append((request, timeout))
            return FakeResponse()

        request_shutdown(
            {
                "RUNPOD_SHUTDOWN_ACTION": "terminate",
                "RUNPOD_POD_ID": "pod123",
                "RUNPOD_API_KEY": "secret",
            },
            allow_terminate=False,
            opener=open_request,
        )

        payload = json.loads(calls[0][0].data.decode("utf-8"))
        self.assertIn("podStop", payload["query"])

    def test_already_deleted_is_success(self):
        def open_request(request, timeout):
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        self.assertTrue(
            request_shutdown(
                {
                    "RUNPOD_SHUTDOWN_ACTION": "terminate",
                    "RUNPOD_POD_ID": "pod123",
                    "RUNPOD_API_KEY": "secret",
                },
                opener=open_request,
            )
        )

    def test_invalid_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "RUNPOD_SHUTDOWN_ACTION"):
            request_shutdown({"RUNPOD_SHUTDOWN_ACTION": "destroy"})

    def test_graphql_errors_fail(self):
        def open_request(request, timeout):
            return FakeResponse(b'{"errors": [{"message": "forbidden"}]}')

        with self.assertRaisesRegex(RuntimeError, "GraphQL"):
            request_shutdown(
                {"RUNPOD_POD_ID": "pod123", "RUNPOD_API_KEY": "secret"},
                opener=open_request,
            )

    def test_auth_errors_are_not_retried(self):
        calls = []

        def open_request(request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 403, "forbidden", {}, None)

        with self.assertRaisesRegex(RuntimeError, "authorization"):
            request_shutdown(
                {"RUNPOD_POD_ID": "pod123", "RUNPOD_API_KEY": "secret"},
                opener=open_request,
            )

        self.assertEqual(len(calls), 1)

    def test_main_does_not_restart_loop_when_shutdown_fails_on_runpod(self):
        from runner import main as runner_main

        with mock.patch.dict(
            "os.environ",
            {"RUNPOD_POD_ID": "pod123", "RUNPOD_API_KEY": "secret", "RUNPOD_SHUTDOWN_ACTION": "stop"},
            clear=True,
        ), mock.patch.object(runner_main.Settings, "from_env", side_effect=RuntimeError("bad config")), mock.patch.object(
            runner_main, "request_shutdown", side_effect=RuntimeError("stop failed")
        ), mock.patch(
            "sys.argv", ["runner"]
        ):
            self.assertEqual(runner_main.main(), 0)


if __name__ == "__main__":
    unittest.main()

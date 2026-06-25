import unittest
from urllib.error import HTTPError

from runner.runpod import request_shutdown, shutdown_action


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


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
        self.assertEqual(request.full_url, "https://rest.runpod.io/v1/pods/pod%20123/stop")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
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

        self.assertEqual(calls[0][0].full_url, "https://rest.runpod.io/v1/pods/pod123")
        self.assertEqual(calls[0][0].method, "DELETE")

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

        self.assertEqual(calls[0][0].full_url, "https://rest.runpod.io/v1/pods/pod123/stop")
        self.assertEqual(calls[0][0].method, "POST")

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


if __name__ == "__main__":
    unittest.main()

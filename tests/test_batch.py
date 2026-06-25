import os
import tempfile
import unittest
from pathlib import Path

from runner.config import Settings
from runner.main import run_batch
from runner.training import ShutdownController


class FakeClient:
    def __init__(self):
        self.uploaded = []
        self.datasets = []

    def download_run(self, run_id, destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "cli_config.yml").write_text(
            f"model_name_or_path: public/model\n"
            f"dataset_dir: /workspace/data/example\n"
            f"output_dir: /workspace/training_artifacts/{run_id}/checkpoints\n",
            encoding="utf-8",
        )

    def download_dataset(self, relative):
        self.datasets.append(str(relative))

    def download_model(self, relative):
        raise AssertionError("public model must not be downloaded by the runner")

    def upload_checkpoints(self, run_id, source):
        self.uploaded.append(run_id)

    def upload_runner_metadata(self, run_id, source):
        self.uploaded.append(f"{run_id}/.runner")


class BatchTests(unittest.TestCase):
    def test_second_run_continues_after_first_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings(
                run_ids=("run0073", "run0074"),
                nextcloud_url="https://example.invalid",
                nextcloud_username="user",
                nextcloud_password="password",
                nextcloud_run_root="/runs",
                nextcloud_data_root="/data",
                nextcloud_model_root="/models",
                wandb_api_key="key",
                wandb_project="project",
                wandb_entity=None,
                hf_token=None,
                workspace_root=Path(temporary),
            )
            client = FakeClient()
            calls = []

            def train(config_path, environment, shutdown, logger):
                calls.append(config_path.parent.name)
                return 2 if len(calls) == 1 else 0

            result = run_batch(settings, client, ShutdownController(1), train)
            self.assertEqual(result, 1)
            self.assertEqual(calls, ["run0073", "run0074"])
            self.assertEqual(client.uploaded, ["run0073", "run0074"])

    def test_training_environment_does_not_receive_nextcloud_credentials(self):
        from runner.main import _training_environment

        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings(
                run_ids=("run0073",),
                nextcloud_url="https://example.invalid",
                nextcloud_username="user",
                nextcloud_password="password",
                nextcloud_run_root="/runs",
                nextcloud_data_root="/data",
                nextcloud_model_root="/models",
                wandb_api_key="key",
                wandb_project="project",
                wandb_entity=None,
                hf_token=None,
                workspace_root=Path(temporary),
            )
            with unittest.mock.patch.dict(
                "os.environ",
                {
                    "NEXTCLOUD_PASSWORD": "secret",
                    "RUNPOD_API_KEY": "pod-secret",
                    "RUNPOD_POD_ID": "pod-id",
                    "RUN_IDS": "run0073",
                    "PATH": "path",
                },
                clear=True,
            ):
                environment = _training_environment(settings, Path(temporary))
            self.assertNotIn("NEXTCLOUD_PASSWORD", environment)
            self.assertNotIn("RUNPOD_API_KEY", environment)
            self.assertNotIn("RUNPOD_POD_ID", environment)
            self.assertNotIn("RUN_IDS", environment)
            self.assertEqual(environment["WANDB_API_KEY"], "key")

    def test_runner_removes_credentials_from_its_process_environment(self):
        from runner.main import _remove_runtime_credentials

        with unittest.mock.patch.dict(
            "os.environ",
            {
                "NEXTCLOUD_PASSWORD": "nextcloud-secret",
                "RUNPOD_API_KEY": "runpod-secret",
                "WANDB_API_KEY": "wandb-secret",
                "HF_TOKEN": "hf-secret",
                "PATH": "path",
            },
            clear=True,
        ):
            _remove_runtime_credentials()
            self.assertEqual(dict(os.environ), {"PATH": "path"})


if __name__ == "__main__":
    unittest.main()

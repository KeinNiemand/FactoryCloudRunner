import tempfile
import unittest
from pathlib import Path

from runner.config import Settings, load_run_config, parse_run_ids
from runner.nextcloud import remote_path


class ConfigTests(unittest.TestCase):
    def test_run_ids_are_strict_and_unique(self):
        self.assertEqual(parse_run_ids("run0073, run0074"), ("run0073", "run0074"))
        for value in ("", "run73", "run0073,run0073", "../run0073"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_run_ids(value)

    def test_cloud_paths_are_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "cli_config.yml").write_text(
                "model_name_or_path: /workspace/models/private/model\n"
                "dataset_dir: /workspace/data/SkyrimCYOA_SFT/llamafactory\n"
                "output_dir: /workspace/training_artifacts/run0073/checkpoints\n",
                encoding="utf-8",
            )
            config = load_run_config(run_dir, "run0073")
            self.assertEqual(str(config.dataset_relative), "SkyrimCYOA_SFT/llamafactory")
            self.assertEqual(str(config.model_relative), "private/model")

    def test_output_dir_must_match_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "cli_config.yml").write_text(
                "model_name_or_path: public/model\n"
                "dataset_dir: /workspace/data/example\n"
                "output_dir: /workspace/training_artifacts/run9999/checkpoints\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "output_dir"):
                load_run_config(run_dir, "run0073")

    def test_arbitrary_absolute_model_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "cli_config.yml").write_text(
                "model_name_or_path: /etc/passwd\n"
                "dataset_dir: /workspace/data/example\n"
                "output_dir: /workspace/training_artifacts/run0073/checkpoints\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Hugging Face ID"):
                load_run_config(run_dir, "run0073")

    def test_logging_dir_must_stay_under_checkpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "cli_config.yml").write_text(
                "model_name_or_path: public/model\n"
                "dataset_dir: /workspace/data/example\n"
                "output_dir: /workspace/training_artifacts/run0073/checkpoints\n"
                "logging_dir: /tmp/logs\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "logging_dir"):
                load_run_config(run_dir, "run0073")

    def test_nextcloud_url_requires_https_without_credentials(self):
        environment = {
            "RUN_IDS": "run0073",
            "NEXTCLOUD_URL": "http://user:pass@example.invalid",
            "NEXTCLOUD_USERNAME": "user",
            "NEXTCLOUD_PASSWORD": "password",
            "NEXTCLOUD_RUN_ROOT": "/runs",
            "NEXTCLOUD_DATA_ROOT": "/data",
            "NEXTCLOUD_MODEL_ROOT": "/models",
            "WANDB_API_KEY": "key",
            "WANDB_PROJECT": "project",
        }
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            Settings.from_env(environment)

    def test_remote_path_preserves_spaces_and_rejects_traversal(self):
        self.assertEqual(remote_path("/AI Models/LLM", "private model"), "nextcloud:AI Models/LLM/private model")
        with self.assertRaises(ValueError):
            remote_path("/runs", "..", "secret")


if __name__ == "__main__":
    unittest.main()

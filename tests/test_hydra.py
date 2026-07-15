import os
import stat
import tempfile
import unittest
import zipfile
from unittest import mock

from adaup.download import hydra
from adaup.download.platforms import detect_platform


class HydraSourceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.platform_info = detect_platform(system="Darwin", machine="arm64")

    def test_env_paths_take_priority(self):
        with mock.patch.dict(
            os.environ,
            {
                hydra.ENV_HYDRA_NODE_PATH: "/tmp/hydra-node",
                hydra.ENV_HYDRA_TUI_PATH: "/tmp/hydra-tui",
                hydra.ENV_HYDRA_DOWNLOAD_URL: "https://example.invalid/{artifact}.zip",
                hydra.ENV_HYDRA_ACTIONS_RUN_URL: "https://github.com/cardano-scaling/hydra/actions/runs/1",
            },
            clear=False,
        ), mock.patch("shutil.which", return_value="/tmp/ignored"):
            source_kind, source_value = hydra.resolve_hydra_source("2.2.0", self.platform_info)
            self.assertEqual(source_kind, "explicit_paths")
            self.assertEqual(source_value, ("/tmp/hydra-node", "/tmp/hydra-tui"))

    def test_path_binaries_take_priority_over_downloads(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "shutil.which",
            side_effect=["/usr/local/bin/hydra-node", "/usr/local/bin/hydra-tui"],
        ):
            source_kind, source_value = hydra.resolve_hydra_source("2.2.0", self.platform_info)
            self.assertEqual(source_kind, "path")
            self.assertEqual(
                source_value,
                ("/usr/local/bin/hydra-node", "/usr/local/bin/hydra-tui"),
            )

    def test_direct_url_takes_priority_over_actions(self):
        with mock.patch.dict(
            os.environ,
            {
                hydra.ENV_HYDRA_DOWNLOAD_URL: "https://example.invalid/{artifact}.zip",
                hydra.ENV_HYDRA_ACTIONS_RUN_URL: "https://github.com/cardano-scaling/hydra/actions/runs/1",
            },
            clear=True,
        ), mock.patch("shutil.which", side_effect=[None, None]):
            source_kind, source_value = hydra.resolve_hydra_source("2.2.0", self.platform_info)
            self.assertEqual(source_kind, "direct_url")
            self.assertEqual(
                source_value,
                "https://example.invalid/hydra-aarch64-darwin-2.2.0.zip",
            )

    def test_parse_github_actions_run_url(self):
        owner, repo, run_id = hydra.parse_github_actions_run_url(
            "https://github.com/cardano-scaling/hydra/actions/runs/27418396480"
        )
        self.assertEqual((owner, repo, run_id), ("cardano-scaling", "hydra", "27418396480"))


class HydraArchiveInstallTests(unittest.TestCase):
    def test_install_hydra_from_nested_zip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = os.path.join(tmp_dir, "hydra-aarch64-darwin-2.2.0.zip")
            bin_dir = os.path.join(tmp_dir, "bin")
            nested_dir = os.path.join(tmp_dir, "artifact_root")
            os.makedirs(nested_dir, exist_ok=True)

            hydra_node_path = os.path.join(nested_dir, "hydra-node")
            hydra_tui_path = os.path.join(nested_dir, "hydra-tui")
            for path in (hydra_node_path, hydra_tui_path):
                with open(path, "w", encoding="utf-8") as file:
                    file.write("#!/usr/bin/env bash\nexit 0\n")
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            with zipfile.ZipFile(archive_path, "w") as zip_file:
                zip_file.write(hydra_node_path, arcname="hydra-aarch64-darwin-2.2.0/hydra-node")
                zip_file.write(hydra_tui_path, arcname="hydra-aarch64-darwin-2.2.0/hydra-tui")

            hydra.install_hydra_from_archive(archive_path, bin_dir)

            self.assertTrue(os.path.isfile(os.path.join(bin_dir, "hydra-node")))
            self.assertTrue(os.path.isfile(os.path.join(bin_dir, "hydra-tui")))


if __name__ == "__main__":
    unittest.main()

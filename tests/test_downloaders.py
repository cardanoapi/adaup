import unittest

from adaup.download.node import build_cardano_node_asset_name
from adaup.download.platforms import detect_platform


class DownloaderResolutionTests(unittest.TestCase):
    def test_cardano_node_asset_name_for_macos_arm64(self):
        platform_info = detect_platform(system="Darwin", machine="arm64")
        self.assertEqual(
            build_cardano_node_asset_name("11.0.1", platform_info),
            "cardano-node-11.0.1-macos-arm64.tar.gz",
        )


if __name__ == "__main__":
    unittest.main()

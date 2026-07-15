import unittest

from adaup.download.platforms import detect_platform


class PlatformDetectionTests(unittest.TestCase):
    def test_detect_darwin_arm64(self):
        platform_info = detect_platform(system="Darwin", machine="arm64")
        self.assertEqual(platform_info.family, "darwin")
        self.assertEqual(platform_info.arch, "arm64")
        self.assertEqual(platform_info.cardano_suffix, "macos-arm64")
        self.assertEqual(platform_info.etcd_suffix, "darwin-arm64")
        self.assertEqual(platform_info.hydra_suffix, "aarch64-darwin")

    def test_detect_linux_amd64(self):
        platform_info = detect_platform(system="Linux", machine="x86_64")
        self.assertEqual(platform_info.family, "linux")
        self.assertEqual(platform_info.arch, "amd64")
        self.assertEqual(platform_info.cardano_suffix, "linux-amd64")
        self.assertEqual(platform_info.etcd_suffix, "linux-amd64")
        self.assertEqual(platform_info.hydra_suffix, "x86_64-linux")

    def test_unsupported_architecture_raises(self):
        with self.assertRaises(ValueError):
            detect_platform(system="Darwin", machine="ppc64")


if __name__ == "__main__":
    unittest.main()

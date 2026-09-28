import os
import unittest
from unittest import mock

from adaup.commands import devnet_docker
from adaup.commands.devnet_smoke import ALL_ACTIONS, _parse_list


class DockerDevnetSettingsTests(unittest.TestCase):
    def load(self, env=None, overrides=None):
        env = {"CARDANO_HOME": "/tmp/adaup-test-home", **(env or {})}
        with mock.patch.dict(os.environ, env, clear=True):
            return devnet_docker.load_settings(overrides or {})

    def test_defaults(self):
        settings = self.load()
        self.assertEqual(settings.dir, "/tmp/adaup-test-home/devnet-docker")
        self.assertEqual(settings.slot_length, 0.2)
        self.assertEqual(settings.epoch_length, 300)
        self.assertEqual(settings.protocol_major, 10)
        # 2h of wall-clock time at 60s epochs.
        self.assertEqual(settings.gov_action_lifetime, 120)
        self.assertEqual(settings.drep_activity, 120)
        self.assertEqual(settings.profiles, ["kuber", "dbsync"])

    def test_env_and_cli_precedence(self):
        settings = self.load(
            env={"ADAUP_DEVNET_EPOCH_LENGTH": "600", "ADAUP_DEVNET_DBSYNC": "0", "ADAUP_DEVNET_KUBER_PORT": "9000"},
            overrides={"epoch_length": 900, "kuber": False},
        )
        self.assertEqual(settings.epoch_length, 900)
        self.assertFalse(settings.kuber)
        self.assertFalse(settings.dbsync)
        self.assertEqual(settings.kuber_port, 9000)
        self.assertEqual(settings.profiles, [])
        self.assertEqual(settings.gov_action_lifetime, 40)

    def test_explicit_lifetime(self):
        settings = self.load(env={"ADAUP_DEVNET_GOV_ACTION_LIFETIME": "7"})
        self.assertEqual(settings.gov_action_lifetime, 7)

    def test_epoch_must_exceed_stability_window(self):
        with self.assertRaises(ValueError):
            self.load(overrides={"epoch_length": 100, "active_slots_coeff": 0.1, "security_param": 10})

    def test_bootstrap_protocol_version_rejected(self):
        with self.assertRaises(ValueError):
            self.load(env={"ADAUP_DEVNET_PROTOCOL_MAJOR": "9"})

    def test_genesis_specs(self):
        settings = self.load()
        shelley = devnet_docker._shelley_spec(settings)
        self.assertEqual(shelley["protocolParams"]["protocolVersion"], {"major": 10, "minor": 0})
        self.assertEqual(shelley["securityParam"], 10)
        self.assertNotIn("staking", shelley)
        conway = devnet_docker._conway_spec(settings)
        self.assertEqual(conway["govActionLifetime"], 120)
        self.assertEqual(conway["dRepDeposit"], 500 * devnet_docker.ADA)
        self.assertEqual(conway["govActionDeposit"], 1000 * devnet_docker.ADA)

    def test_packaged_assets_exist(self):
        for name in ("docker-compose.yml", "db-sync-config.json", "anchor-server.sh"):
            self.assertTrue(os.path.isfile(devnet_docker._asset("docker", name)), name)


class SmokeActionParsingTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(_parse_list(None, ["info"], ALL_ACTIONS), ["info"])
        self.assertEqual(_parse_list("all", [], ALL_ACTIONS), ALL_ACTIONS)
        self.assertEqual(_parse_list("none", ALL_ACTIONS, ALL_ACTIONS), [])
        self.assertEqual(_parse_list("treasury, info", [], ALL_ACTIONS), ["treasury", "info"])
        with self.assertRaises(RuntimeError):
            _parse_list("bogus", [], ALL_ACTIONS)


if __name__ == "__main__":
    unittest.main()

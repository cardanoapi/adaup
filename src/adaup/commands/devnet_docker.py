#!/usr/bin/env python
"""
Docker devnet: a single block-producing Conway node with on-chain governance,
plus optional kuber, cardano-db-sync + postgres, and an anchor file server,
all in docker. Only docker is needed on the host; cardano-cli runs inside the
node image.

Genesis is regenerated on every `up` (systemStart = now), so the postgres and
node volumes are always recreated as well.
"""

import json
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from fractions import Fraction

from adaup.commands.node_support import ensure_dir, get_cardano_home

DEVNET_MAGIC = 42
ADA = 1_000_000

NODE_IMAGE = "ghcr.io/intersectmbo/cardano-node:11.0.1"
# ghcr.io/dquadrant/kuber:v4.2.0 (the node 11.0.1 build) currently has a broken
# manifest list on ghcr; override with ADAUP_DEVNET_KUBER_IMAGE once it is fixed.
KUBER_IMAGE = "ghcr.io/dquadrant/kuber:1009cf9eefa47a3fccafad75c7aa404088f8e8ac"
DBSYNC_IMAGE = "ghcr.io/intersectmbo/cardano-db-sync:13.7.2.1"
POSTGRES_IMAGE = "postgres:17-alpine"

# CLI flag name -> (env var, type, default). A default of None is derived later.
SETTINGS_SPEC = {
    "dir": ("ADAUP_DEVNET_DIR", str, None),
    "project": ("ADAUP_DEVNET_PROJECT", str, "adaup-devnet"),
    "slot_length": ("ADAUP_DEVNET_SLOT_LENGTH", float, 0.2),
    "epoch_length": ("ADAUP_DEVNET_EPOCH_LENGTH", int, 300),
    "active_slots_coeff": ("ADAUP_DEVNET_ACTIVE_SLOTS_COEFF", float, 0.25),
    "security_param": ("ADAUP_DEVNET_SECURITY_PARAM", int, 10),
    "protocol_major": ("ADAUP_DEVNET_PROTOCOL_MAJOR", int, 10),
    "live_seconds": ("ADAUP_DEVNET_LIVE_SECONDS", int, 7200),
    "gov_action_lifetime": ("ADAUP_DEVNET_GOV_ACTION_LIFETIME", int, None),
    "drep_activity": ("ADAUP_DEVNET_DREP_ACTIVITY", int, None),
    "drep_deposit_ada": ("ADAUP_DEVNET_DREP_DEPOSIT_ADA", int, 500),
    "gov_action_deposit_ada": ("ADAUP_DEVNET_GOV_ACTION_DEPOSIT_ADA", int, 1000),
    "key_deposit_ada": ("ADAUP_DEVNET_KEY_DEPOSIT_ADA", int, 2),
    "pool_deposit_ada": ("ADAUP_DEVNET_POOL_DEPOSIT_ADA", int, 500),
    "committee_size": ("ADAUP_DEVNET_COMMITTEE_SIZE", int, 3),
    "committee_threshold": ("ADAUP_DEVNET_COMMITTEE_THRESHOLD", str, "2/3"),
    "committee_min_size": ("ADAUP_DEVNET_COMMITTEE_MIN_SIZE", int, 0),
    "committee_max_term": ("ADAUP_DEVNET_COMMITTEE_MAX_TERM", int, 10000),
    "faucet_ada": ("ADAUP_DEVNET_FAUCET_ADA", int, 500_000_000),
    "pool_stake_ada": ("ADAUP_DEVNET_POOL_STAKE_ADA", int, 50_000_000),
    "kuber": ("ADAUP_DEVNET_KUBER", bool, True),
    "dbsync": ("ADAUP_DEVNET_DBSYNC", bool, True),
    "bind": ("ADAUP_DEVNET_BIND", str, "127.0.0.1"),
    "kuber_port": ("ADAUP_DEVNET_KUBER_PORT", int, 8081),
    "postgres_port": ("ADAUP_DEVNET_POSTGRES_PORT", int, 5433),
    "anchor_port": ("ADAUP_DEVNET_ANCHOR_PORT", int, 8090),
    "postgres_user": ("ADAUP_DEVNET_POSTGRES_USER", str, "postgres"),
    "postgres_password": ("ADAUP_DEVNET_POSTGRES_PASSWORD", str, "postgres"),
    "postgres_db": ("ADAUP_DEVNET_POSTGRES_DB", str, "cexplorer"),
    "node_image": ("ADAUP_DEVNET_NODE_IMAGE", str, NODE_IMAGE),
    "kuber_image": ("ADAUP_DEVNET_KUBER_IMAGE", str, KUBER_IMAGE),
    "dbsync_image": ("ADAUP_DEVNET_DBSYNC_IMAGE", str, DBSYNC_IMAGE),
    "postgres_image": ("ADAUP_DEVNET_POSTGRES_IMAGE", str, POSTGRES_IMAGE),
    "timeout": ("ADAUP_DEVNET_TIMEOUT", int, 600),
    # Comma-separated IPFS gateways db-sync resolves ipfs:// anchors through
    # (its `ipfs_gateway` setting). Empty keeps db-sync's default.
    "ipfs_gateways": ("ADAUP_DEVNET_IPFS_GATEWAYS", str, ""),
}


@dataclass
class DockerDevnetSettings:
    dir: str
    project: str
    slot_length: float
    epoch_length: int
    active_slots_coeff: float
    security_param: int
    protocol_major: int
    live_seconds: int
    gov_action_lifetime: int
    drep_activity: int
    drep_deposit_ada: int
    gov_action_deposit_ada: int
    key_deposit_ada: int
    pool_deposit_ada: int
    committee_size: int
    committee_threshold: str
    committee_min_size: int
    committee_max_term: int
    faucet_ada: int
    pool_stake_ada: int
    kuber: bool
    dbsync: bool
    bind: str
    kuber_port: int
    postgres_port: int
    anchor_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str
    node_image: str
    kuber_image: str
    dbsync_image: str
    postgres_image: str
    timeout: int
    ipfs_gateways: str = ""

    @property
    def epoch_seconds(self):
        return self.slot_length * self.epoch_length

    @property
    def network(self):
        return self.project

    @property
    def compose_file(self):
        return os.path.join(self.dir, "docker-compose.yml")

    @property
    def profiles(self):
        return [name for name, enabled in (("kuber", self.kuber), ("dbsync", self.dbsync)) if enabled]


def log(message=""):
    print(message, flush=True)


def _parse_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def load_settings(overrides=None):
    """
    Resolve settings with precedence: explicit overrides (CLI) > ADAUP_DEVNET_* env > defaults.
    """
    overrides = overrides or {}
    values = {}
    for name, (env_name, cast, default) in SETTINGS_SPEC.items():
        value = overrides.get(name)
        if value is None and os.environ.get(env_name, "") != "":
            raw = os.environ[env_name]
            value = _parse_bool(raw) if cast is bool else cast(raw)
        if value is None:
            value = default
        values[name] = value

    if not values["dir"]:
        values["dir"] = os.path.join(get_cardano_home(), "devnet-docker")
    values["dir"] = os.path.abspath(os.path.expanduser(values["dir"]))

    live_epochs = max(2, math.ceil(values["live_seconds"] / (values["slot_length"] * values["epoch_length"])))
    if not values["gov_action_lifetime"]:
        values["gov_action_lifetime"] = live_epochs
    if not values["drep_activity"]:
        values["drep_activity"] = live_epochs

    settings = DockerDevnetSettings(**values)
    validate_settings(settings)
    return settings


def load_saved_settings(settings):
    """
    Settings of the devnet already generated in settings.dir (from devnet.json),
    so status/smoke/down act on what is running rather than on the current env.
    """
    path = os.path.join(settings.dir, "devnet.json")
    if not os.path.isfile(path):
        return settings
    saved = _read_json(path).get("settings", {})
    known = {name: saved[name] for name in SETTINGS_SPEC if name in saved}
    known["dir"] = settings.dir
    return DockerDevnetSettings(**{**asdict(settings), **known})


def validate_settings(settings):
    k = settings.security_param
    f = settings.active_slots_coeff
    if not 0 < f <= 1:
        raise ValueError("active slots coefficient must be in (0, 1]")
    # The randomness stabilisation window (4k/f) must fit inside an epoch,
    # otherwise the node cannot compute the epoch nonce.
    window = math.ceil(4 * k / f)
    if settings.epoch_length <= window:
        raise ValueError(
            f"epoch length {settings.epoch_length} must be larger than 4k/f = {window} "
            f"(k={k}, f={f}); raise the epoch length or the active slots coefficient"
        )
    if settings.protocol_major < 10:
        raise ValueError("protocol major version must be >= 10 (9 is the governance bootstrap phase)")
    threshold = Fraction(settings.committee_threshold)
    if not 0 <= threshold <= 1:
        raise ValueError("committee threshold must be between 0 and 1")
    if settings.committee_size < 1:
        raise ValueError("committee size must be at least 1")


def _package_devnet_root():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "devnet")


def _asset(*parts):
    return os.path.join(_package_devnet_root(), *parts)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def _host_ids():
    if hasattr(os, "getuid"):
        return os.getuid(), os.getgid()
    return 0, 0


# ---------------------------------------------------------------------------
# docker helpers
# ---------------------------------------------------------------------------

def require_docker():
    if shutil.which("docker") is None:
        log("Error: docker is required for the docker devnet.")
        sys.exit(1)
    result = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        log("Error: the docker compose plugin is required for the docker devnet.")
        sys.exit(1)


def compose_env(settings):
    # The rendered .env file is the source of truth for the compose file, so
    # keep ADAUP_DEVNET_* values from the calling shell out of the way.
    env = {key: value for key, value in os.environ.items() if not key.startswith("ADAUP_DEVNET_")}
    env["COMPOSE_PROFILES"] = ",".join(settings.profiles)
    return env


def compose(settings, *args, check=True, capture=False, all_profiles=False):
    cmd = [
        "docker", "compose",
        "--project-name", settings.project,
        "--project-directory", settings.dir,
        "-f", settings.compose_file,
        *args,
    ]
    env = compose_env(settings)
    if all_profiles:
        env["COMPOSE_PROFILES"] = "kuber,dbsync"
    result = subprocess.run(
        cmd,
        env=env,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise RuntimeError(f"docker compose {' '.join(args)} failed ({result.returncode}) {detail}")
    return result


def node_exec(settings, args, check=True):
    """Run a command inside the running cardano-node container and return stdout."""
    result = compose(settings, "exec", "-T", "cardano-node", *args, check=False, capture=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def node_cli(settings, *args, check=True):
    return node_exec(settings, ["cardano-cli", *args], check=check)


def run_cli_batch(settings, commands):
    """
    Run several offline cardano-cli commands in one throwaway node-image
    container as the host user, with the devnet dir mounted at /devnet.
    Returns the stdout of each command.
    """
    marker = "__ADAUP_SPLIT__"
    script = f"set -e\n" + f"\necho {marker}\n".join(
        " ".join(shlex.quote(part) for part in ["cardano-cli", *command]) for command in commands
    )
    uid, gid = _host_ids()
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--user", f"{uid}:{gid}",
            "-e", "HOME=/tmp",
            "-v", f"{settings.dir}:/devnet",
            "-w", "/devnet",
            "--entrypoint", "bash",
            settings.node_image,
            "-c", script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cardano-cli failed in {settings.node_image}: {result.stderr.strip()}")
    return [part.strip() for part in result.stdout.split(marker)]


# ---------------------------------------------------------------------------
# genesis and configuration
# ---------------------------------------------------------------------------

def _shelley_spec(settings):
    spec = _read_json(_asset("cardano-node", "genesis-shelley.json"))
    spec.pop("staking", None)
    spec["initialFunds"] = {}
    spec.update(
        {
            "networkMagic": DEVNET_MAGIC,
            "networkId": "Testnet",
            "epochLength": settings.epoch_length,
            "slotLength": settings.slot_length,
            "activeSlotsCoeff": settings.active_slots_coeff,
            "securityParam": settings.security_param,
            "maxLovelaceSupply": 45_000_000_000 * ADA,
            "updateQuorum": 1,
        }
    )
    spec["protocolParams"].update(
        {
            "protocolVersion": {"major": settings.protocol_major, "minor": 0},
            "decentralisationParam": 0,
            "keyDeposit": settings.key_deposit_ada * ADA,
            "poolDeposit": settings.pool_deposit_ada * ADA,
            "minFeeA": 44,
            "minFeeB": 155381,
            "maxTxSize": 16384,
            "maxBlockBodySize": 90112,
            "maxBlockHeaderSize": 1100,
            "eMax": 18,
            "nOpt": 100,
            "a0": 0.3,
            "rho": 0.003,
            "tau": 0.2,
            "minPoolCost": 0,
            "minUTxOValue": 0,
        }
    )
    return spec


def _conway_spec(settings):
    spec = _read_json(_asset("cardano-node", "genesis-conway.json"))
    spec.update(
        {
            "poolVotingThresholds": {
                "committeeNormal": 0.51,
                "committeeNoConfidence": 0.51,
                "hardForkInitiation": 0.51,
                "motionNoConfidence": 0.51,
                "ppSecurityGroup": 0.51,
            },
            "dRepVotingThresholds": {
                "motionNoConfidence": 0.67,
                "committeeNormal": 0.67,
                "committeeNoConfidence": 0.6,
                "updateToConstitution": 0.75,
                "hardForkInitiation": 0.6,
                "ppNetworkGroup": 0.67,
                "ppEconomicGroup": 0.67,
                "ppTechnicalGroup": 0.67,
                "ppGovGroup": 0.75,
                "treasuryWithdrawal": 0.67,
            },
            "committeeMinSize": settings.committee_min_size,
            "committeeMaxTermLength": settings.committee_max_term,
            "govActionLifetime": settings.gov_action_lifetime,
            "govActionDeposit": settings.gov_action_deposit_ada * ADA,
            "dRepDeposit": settings.drep_deposit_ada * ADA,
            "dRepActivity": settings.drep_activity,
            "minFeeRefScriptCostPerByte": 15,
        }
    )
    return spec


def _constitution_anchor():
    body = {
        "@context": {"@language": "en-us", "CIP100": "https://github.com/cardano-foundation/CIPs/blob/master/CIP-0100/README.md#"},
        "hashAlgorithm": "blake2b-256",
        "body": {"title": "adaup devnet constitution", "abstract": "Genesis constitution of the adaup docker devnet. No guardrail script."},
        "authors": [],
    }
    return json.dumps(body, indent=2).encode("utf-8")


def blake2b_256(data):
    import hashlib

    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _fresh_layout(settings):
    ensure_dir(settings.dir)
    for sub in ("config", "keys", "anchors", "smoke", "tmp"):
        path = os.path.join(settings.dir, sub)
        if os.path.isdir(path):
            shutil.rmtree(path)
    for sub in ("config", "keys", "anchors", "smoke", "tmp"):
        ensure_dir(os.path.join(settings.dir, sub))


def _move(src, dst):
    ensure_dir(os.path.dirname(dst))
    shutil.move(src, dst)


def generate_devnet(settings):
    """Generate keys, genesis files, node/db-sync config, .env and compose file."""
    _fresh_layout(settings)
    base = settings.dir
    tmp = os.path.join(base, "tmp")
    config_dir = os.path.join(base, "config")
    keys_dir = os.path.join(base, "keys")

    _write_json(os.path.join(tmp, "spec-shelley.json"), _shelley_spec(settings))
    shutil.copy2(_asset("cardano-node", "genesis-alonzo.json"), os.path.join(tmp, "spec-alonzo.json"))
    _write_json(os.path.join(tmp, "spec-conway.json"), _conway_spec(settings))

    log("Generating devnet keys and genesis...")
    run_cli_batch(
        settings,
        [[
            "conway", "genesis", "create-testnet-data",
            "--spec-shelley", "tmp/spec-shelley.json",
            "--spec-alonzo", "tmp/spec-alonzo.json",
            "--spec-conway", "tmp/spec-conway.json",
            "--genesis-keys", "1",
            "--pools", "1",
            "--stake-delegators", "1",
            "--committee-keys", str(settings.committee_size),
            "--utxo-keys", "1",
            "--total-supply", str((settings.faucet_ada + settings.pool_stake_ada) * ADA),
            "--delegated-supply", str(settings.pool_stake_ada * ADA),
            "--testnet-magic", str(DEVNET_MAGIC),
            "--out-dir", "tmp/testnet",
        ]],
    )
    data = os.path.join(tmp, "testnet")

    # Keys into a stable layout.
    _move(os.path.join(data, "pools-keys", "pool1"), os.path.join(keys_dir, "pool"))
    _move(os.path.join(data, "stake-delegators", "delegator1"), os.path.join(keys_dir, "pool-delegator"))
    faucet_dir = ensure_dir(os.path.join(keys_dir, "faucet"))
    _move(os.path.join(data, "utxo-keys", "utxo1", "utxo.skey"), os.path.join(faucet_dir, "payment.skey"))
    _move(os.path.join(data, "utxo-keys", "utxo1", "utxo.vkey"), os.path.join(faucet_dir, "payment.vkey"))
    committee_dir = ensure_dir(os.path.join(keys_dir, "committee"))
    for index in range(1, settings.committee_size + 1):
        _move(os.path.join(data, "cc-keys", f"cc{index}"), os.path.join(committee_dir, f"cc{index}"))
    _move(os.path.join(data, "genesis-keys"), os.path.join(keys_dir, "genesis"))
    _move(os.path.join(data, "delegate-keys"), os.path.join(keys_dir, "genesis-delegates"))
    _move(os.path.join(data, "byron-gen-command"), os.path.join(keys_dir, "byron-genesis"))
    for path in _walk_files(keys_dir):
        if path.endswith(".md"):
            os.remove(path)
        else:
            os.chmod(path, 0o600)

    # Genesis files, patched with the settings create-testnet-data does not apply.
    start = int(time.time())
    shelley = _read_json(os.path.join(data, "shelley-genesis.json"))
    spec_shelley = _shelley_spec(settings)
    for key in ("epochLength", "slotLength", "activeSlotsCoeff", "securityParam", "maxLovelaceSupply", "updateQuorum"):
        shelley[key] = spec_shelley[key]
    shelley["protocolParams"] = spec_shelley["protocolParams"]
    shelley["systemStart"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start))
    # create-testnet-data spreads the supply across more holders than we use;
    # pin the faucet (enterprise address) and the pool delegator to exact amounts.
    shelley["initialFunds"] = {
        address: (settings.faucet_ada if address.startswith("60") else settings.pool_stake_ada) * ADA
        for address in shelley["initialFunds"]
    }

    byron = _read_json(os.path.join(data, "byron-genesis.json"))
    byron["startTime"] = start
    byron["protocolConsts"]["k"] = settings.security_param
    byron["blockVersionData"]["slotDuration"] = str(int(round(settings.slot_length * 1000)))

    constitution = _constitution_anchor()
    constitution_file = "constitution.jsonld"
    with open(os.path.join(base, "anchors", constitution_file), "wb") as file:
        file.write(constitution)

    conway = _read_json(os.path.join(data, "conway-genesis.json"))
    threshold = Fraction(settings.committee_threshold)
    conway["committee"] = {
        # Explicit epochs: the default max-Word64 term renders as a float.
        "members": {member: settings.committee_max_term for member in conway["committee"]["members"]},
        "threshold": {"numerator": threshold.numerator, "denominator": threshold.denominator},
    }
    conway["constitution"] = {
        "anchor": {"url": f"http://anchors:8080/{constitution_file}", "dataHash": blake2b_256(constitution)}
    }

    _write_json(os.path.join(config_dir, "byron-genesis.json"), byron)
    _write_json(os.path.join(config_dir, "shelley-genesis.json"), shelley)
    shutil.copy2(os.path.join(data, "alonzo-genesis.json"), os.path.join(config_dir, "alonzo-genesis.json"))
    _write_json(os.path.join(config_dir, "conway-genesis.json"), conway)
    shutil.copy2(os.path.join(data, "dijkstra-genesis.json"), os.path.join(config_dir, "dijkstra-genesis.json"))

    (
        byron_hash, shelley_hash, alonzo_hash, conway_hash, dijkstra_hash,
        faucet_addr, delegator_addr, pool_id, *cc_hashes,
    ) = run_cli_batch(
        settings,
        [
            ["byron", "genesis", "print-genesis-hash", "--genesis-json", "config/byron-genesis.json"],
            ["hash", "genesis-file", "--genesis", "config/shelley-genesis.json"],
            ["hash", "genesis-file", "--genesis", "config/alonzo-genesis.json"],
            ["hash", "genesis-file", "--genesis", "config/conway-genesis.json"],
            ["hash", "genesis-file", "--genesis", "config/dijkstra-genesis.json"],
            ["conway", "address", "build", "--payment-verification-key-file", "keys/faucet/payment.vkey",
             "--testnet-magic", str(DEVNET_MAGIC)],
            ["conway", "address", "build", "--payment-verification-key-file", "keys/pool-delegator/payment.vkey",
             "--stake-verification-key-file", "keys/pool-delegator/staking.vkey", "--testnet-magic", str(DEVNET_MAGIC)],
            ["conway", "stake-pool", "id", "--cold-verification-key-file", "keys/pool/cold.vkey", "--output-bech32"],
            *[
                ["conway", "governance", "committee", "key-hash", "--verification-key-file",
                 f"keys/committee/cc{index}/cc.cold.vkey"]
                for index in range(1, settings.committee_size + 1)
            ],
        ],
    )
    for path, value in (
        (os.path.join(faucet_dir, "payment.addr"), faucet_addr),
        (os.path.join(keys_dir, "pool-delegator", "payment.addr"), delegator_addr),
        (os.path.join(keys_dir, "pool", "pool.id"), pool_id),
    ):
        with open(path, "w", encoding="utf-8") as file:
            file.write(value + "\n")

    node_config = _read_json(_asset("cardano-node", "cardano-node.json"))
    node_config.update(
        {
            "ByronGenesisFile": "byron-genesis.json",
            "ByronGenesisHash": byron_hash,
            "ShelleyGenesisFile": "shelley-genesis.json",
            "ShelleyGenesisHash": shelley_hash,
            "AlonzoGenesisFile": "alonzo-genesis.json",
            "AlonzoGenesisHash": alonzo_hash,
            "ConwayGenesisFile": "conway-genesis.json",
            "ConwayGenesisHash": conway_hash,
            "DijkstraGenesisFile": "dijkstra-genesis.json",
            "DijkstraGenesisHash": dijkstra_hash,
            "RequiresNetworkMagic": "RequiresMagic",
            "ExperimentalHardForksEnabled": False,
            "ExperimentalProtocolsEnabled": False,
            "PeerSharing": False,
        }
    )
    _write_json(os.path.join(config_dir, "cardano-node.json"), node_config)
    shutil.copy2(_asset("cardano-node", "topology.json"), os.path.join(config_dir, "topology.json"))
    dbsync_config = _read_json(_asset("docker", "db-sync-config.json"))
    gateways = [g.strip() for g in (settings.ipfs_gateways or "").split(",") if g.strip()]
    if gateways:
        dbsync_config["ipfs_gateway"] = gateways
    _write_json(os.path.join(config_dir, "db-sync-config.json"), dbsync_config)
    shutil.copy2(_asset("docker", "anchor-server.sh"), os.path.join(config_dir, "anchor-server.sh"))
    shutil.copy2(_asset("docker", "docker-compose.yml"), settings.compose_file)
    _write_env_file(settings)
    shutil.rmtree(tmp)

    info = {
        "networkMagic": DEVNET_MAGIC,
        "systemStart": shelley["systemStart"],
        "slotLength": settings.slot_length,
        "epochLength": settings.epoch_length,
        "activeSlotsCoeff": settings.active_slots_coeff,
        "securityParam": settings.security_param,
        "protocolVersion": settings.protocol_major,
        "govActionLifetime": settings.gov_action_lifetime,
        "dRepActivity": settings.drep_activity,
        "dir": settings.dir,
        "composeFile": settings.compose_file,
        "dockerNetwork": settings.network,
        "volumes": {
            "ipc": f"{settings.network}-ipc",
            "config": f"{settings.network}-config",
        },
        "socketPath": "/ipc/node.socket",
        "services": {
            "cardano-node": {"host": "cardano-node", "port": 3001},
            "kuber": {"enabled": settings.kuber, "url": "http://kuber:8081",
                      "hostUrl": f"http://{settings.bind}:{settings.kuber_port}"},
            "postgres": {"enabled": settings.dbsync, "host": "postgres", "port": 5432,
                         "hostPort": settings.postgres_port, "user": settings.postgres_user,
                         "password": settings.postgres_password, "database": settings.postgres_db},
            "anchors": {"url": "http://anchors:8080", "hostUrl": f"http://{settings.bind}:{settings.anchor_port}"},
        },
        "faucet": {"address": faucet_addr, "skey": "keys/faucet/payment.skey", "vkey": "keys/faucet/payment.vkey"},
        "pool": {"id": pool_id, "dir": "keys/pool"},
        "committee": {
            "threshold": settings.committee_threshold,
            "members": [
                {"coldKeyHash": key_hash, "dir": f"keys/committee/cc{index}", "expiryEpoch": settings.committee_max_term}
                for index, key_hash in enumerate(cc_hashes, start=1)
            ],
        },
        "settings": asdict(settings),
    }
    _write_json(os.path.join(base, "devnet.json"), info)
    return info


def _walk_files(root):
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            yield os.path.join(dirpath, name)


def _write_env_file(settings):
    uid, gid = _host_ids()
    values = {
        "ADAUP_DEVNET_PROJECT": settings.project,
        "ADAUP_DEVNET_NETWORK": settings.network,
        "ADAUP_DEVNET_DIR": settings.dir,
        "ADAUP_DEVNET_MAGIC": DEVNET_MAGIC,
        "ADAUP_DEVNET_UID": uid,
        "ADAUP_DEVNET_GID": gid,
        "ADAUP_DEVNET_BIND": settings.bind,
        "ADAUP_DEVNET_KUBER_PORT": settings.kuber_port,
        "ADAUP_DEVNET_POSTGRES_PORT": settings.postgres_port,
        "ADAUP_DEVNET_ANCHOR_PORT": settings.anchor_port,
        "ADAUP_DEVNET_POSTGRES_USER": settings.postgres_user,
        "ADAUP_DEVNET_POSTGRES_PASSWORD": settings.postgres_password,
        "ADAUP_DEVNET_POSTGRES_DB": settings.postgres_db,
        "ADAUP_DEVNET_NODE_IMAGE": settings.node_image,
        "ADAUP_DEVNET_KUBER_IMAGE": settings.kuber_image,
        "ADAUP_DEVNET_DBSYNC_IMAGE": settings.dbsync_image,
        "ADAUP_DEVNET_POSTGRES_IMAGE": settings.postgres_image,
        "COMPOSE_PROFILES": ",".join(settings.profiles),
    }
    path = os.path.join(settings.dir, ".env")
    with open(path, "w", encoding="utf-8") as file:
        for key, value in values.items():
            file.write(f"{key}={value}\n")
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------

def query_tip(settings):
    output = node_cli(settings, "query", "tip", "--testnet-magic", str(DEVNET_MAGIC), check=False)
    try:
        return json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None


def _wait_for(description, predicate, timeout, interval=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise RuntimeError(f"Timed out after {timeout}s waiting for {description}")


def wait_for_blocks(settings, min_block=2):
    def producing():
        tip = query_tip(settings)
        return tip if tip and tip.get("block", 0) >= min_block else None

    return _wait_for("the node to produce blocks", producing, settings.timeout)


def _container_health(settings, service):
    result = compose(settings, "ps", "--format", "json", service, check=False, capture=True)
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries = json.loads(line)
        except json.JSONDecodeError:
            continue
        for entry in entries if isinstance(entries, list) else [entries]:
            if entry.get("Service") == service:
                return entry.get("Health") or entry.get("State")
    return None


def wait_for_healthy(settings, services):
    for service in services:
        log(f"Waiting for {service} to become healthy...")
        _wait_for(f"{service} health", lambda s=service: _container_health(settings, s) == "healthy",
                  settings.timeout, interval=2.0)


def _remove_stack(settings):
    if os.path.isfile(settings.compose_file) and os.path.isfile(os.path.join(settings.dir, ".env")):
        compose(settings, "down", "--volumes", "--remove-orphans", check=False, all_profiles=True)
    # Also catch volumes left behind by a stack started from another directory.
    for suffix in ("config", "ipc", "node-db", "pgdata", "dbsync-state"):
        subprocess.run(
            ["docker", "volume", "rm", "-f", f"{settings.network}-{suffix}"],
            capture_output=True,
            check=False,
        )


def print_summary(settings, info, tip=None):
    log("")
    log("Docker devnet is up.")
    if tip:
        log(f"  tip:           block {tip.get('block')} slot {tip.get('slot')} epoch {tip.get('epoch')}")
    log(f"  directory:     {settings.dir}  (see devnet.json)")
    log(f"  network:       {settings.network}  (docker network; volumes {settings.network}-ipc, {settings.network}-config)")
    log(f"  node socket:   /ipc/node.socket in volume {settings.network}-ipc, magic {DEVNET_MAGIC}")
    log(f"  faucet:        {info['faucet']['address']}")
    log(f"                 {os.path.join(settings.dir, 'keys/faucet/payment.skey')}")
    log(f"  pool:          {info['pool']['id']}")
    if settings.kuber:
        log(f"  kuber:         http://{settings.bind}:{settings.kuber_port}  (http://kuber:8081 in network)")
    if settings.dbsync:
        log(
            f"  postgres:      postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.bind}:{settings.postgres_port}/{settings.postgres_db}  (postgres:5432 in network)"
        )
    log(f"  anchors:       http://{settings.bind}:{settings.anchor_port}  (http://anchors:8080 in network)")
    log(f"  epoch:         {settings.epoch_seconds:g}s, gov action lifetime {settings.gov_action_lifetime} epochs")
    log(f"  stop:          cardano devnet down --docker --dir {settings.dir}")


def devnet_up(settings, detach=True, wait=False):
    require_docker()
    log(f"Preparing docker devnet in {settings.dir}")
    _remove_stack(settings)
    info = generate_devnet(settings)
    started = time.time()
    compose(settings, "up", "--detach", "--remove-orphans")
    log("Waiting for the node to produce blocks...")
    tip = wait_for_blocks(settings)
    log(f"Node is producing blocks ({time.time() - started:.1f}s after start).")
    if wait:
        wait_for_healthy(settings, [s for s, on in (("kuber", settings.kuber), ("db-sync", settings.dbsync)) if on])
    print_summary(settings, info, tip)
    if detach:
        return info

    log("\nFollowing logs, press Ctrl+C to stop and remove the devnet.")

    def _interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)
    try:
        compose(settings, "logs", "--follow", "--tail", "20", check=False)
    except KeyboardInterrupt:
        pass
    finally:
        devnet_down(settings)
    return info


def devnet_down(settings):
    require_docker()
    log(f"Removing docker devnet {settings.project} (containers, volumes, network)...")
    _remove_stack(settings)
    log("Docker devnet removed. Generated files are kept in " + settings.dir)


def devnet_status(settings):
    require_docker()
    if not os.path.isfile(settings.compose_file):
        log(f"No docker devnet found in {settings.dir}")
        return
    compose(settings, "ps", check=False, all_profiles=True)
    tip = query_tip(settings)
    if tip:
        log(json.dumps(tip, indent=2))

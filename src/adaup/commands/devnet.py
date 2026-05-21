#!/usr/bin/env python

import json
import os
import shutil
import signal
import subprocess
import time

from adaup.commands.cardano_cli import CardanoCLI, WalletStore
from adaup.commands.node_support import (
    build_node_run_command,
    ensure_dir,
    ensure_node_binaries,
    get_cardano_home,
    prepare_node_dirs,
)
from adaup.download.node import DEFAULT_CARDANO_NODE_VERSION

DEVNET_MAGIC = 42
DEVNET_FUNDING_LOVELACE = 1_000_000_000_000


def _package_devnet_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "devnet", "cardano-node")


def _copy_devnet_assets(config_dir):
    source_dir = _package_devnet_dir()
    if not os.path.isdir(source_dir):
        raise RuntimeError(f"Missing packaged devnet assets at {source_dir}")

    ensure_dir(config_dir)
    for entry in os.listdir(source_dir):
        src = os.path.join(source_dir, entry)
        dst = os.path.join(config_dir, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def _reset_devnet_state(network_dir, keys_dir):
    if os.path.isdir(network_dir):
        shutil.rmtree(network_dir)

    temp_dir = os.path.join(keys_dir, "tmp")
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir)


def _prepare_devnet_configs(config_dir):
    _copy_devnet_assets(config_dir)

    byron_genesis = os.path.join(config_dir, "genesis-byron.json")
    with open(byron_genesis, "r", encoding="utf-8") as file:
        byron_data = json.load(file)
    byron_data["startTime"] = int(time.time())
    with open(byron_genesis, "w", encoding="utf-8") as file:
        json.dump(byron_data, file, indent=4)

    shelley_genesis = os.path.join(config_dir, "genesis-shelley.json")
    with open(shelley_genesis, "r", encoding="utf-8") as file:
        shelley_data = json.load(file)
    shelley_data["systemStart"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(shelley_genesis, "w", encoding="utf-8") as file:
        json.dump(shelley_data, file, indent=4)

    for filename in ("faucet.sk", "faucet.vk", "kes.skey", "vrf.skey"):
        os.chmod(os.path.join(config_dir, filename), 0o600)

    return config_dir


def _ensure_wallet(cli, keys_dir):
    store = WalletStore(keys_dir)
    return store.gen_wallet(cli)


def _query_utxos(cli, address, out_file):
    cli.cardano_cli(
        "query",
        "utxo",
        ["--address", address, "--out-file", out_file],
        include_network=True,
        include_socket=True,
    )
    with open(out_file, "r", encoding="utf-8") as file:
        return json.load(file)


def _wait_for_socket(cardano_cli_path, socket_path, process, timeout_seconds=90):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Devnet node exited early with code {process.returncode}")
        if os.path.exists(socket_path):
            result = subprocess.run(
                [
                    cardano_cli_path,
                    "query",
                    "tip",
                    f"--testnet-magic={DEVNET_MAGIC}",
                    "--socket-path",
                    socket_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for devnet socket at {socket_path}")


def _wait_for_utxo(cli, wallet, temp_dir, timeout_seconds=60):
    out_file = os.path.join(temp_dir, "wallet-utxo.json")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        utxos = _query_utxos(cli, wallet.address, out_file)
        if utxos:
            return
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for funds at {wallet.address}")


def _fund_wallet(cli, wallet, config_dir, temp_dir):
    wallet_utxo_file = os.path.join(temp_dir, "wallet-utxo.json")
    existing_utxos = _query_utxos(cli, wallet.address, wallet_utxo_file)
    if existing_utxos:
        total = sum(item.get("value", {}).get("lovelace", 0) for item in existing_utxos.values())
        print(f"Devnet wallet already funded with {total} lovelace.")
        return

    faucet_vkey = os.path.join(config_dir, "faucet.vk")
    faucet_skey = os.path.join(config_dir, "faucet.sk")
    faucet_addr = cli.cardano_cli_conway(
        "address",
        "build",
        ["--payment-verification-key-file", faucet_vkey, f"--testnet-magic={DEVNET_MAGIC}"],
    )

    faucet_utxo_file = os.path.join(temp_dir, "faucet-utxo.json")
    faucet_utxos = _query_utxos(cli, faucet_addr, faucet_utxo_file)
    if not faucet_utxos:
        raise RuntimeError("Devnet faucet has no UTxOs to fund the default wallet.")

    faucet_txin = next(iter(faucet_utxos.keys()))
    tx_body = os.path.join(temp_dir, "devnet-fund.raw")
    signed_tx = os.path.join(temp_dir, "devnet-fund.signed")

    cli.cardano_cli_conway(
        "transaction",
        "build",
        [
            "--cardano-mode",
            "--change-address",
            faucet_addr,
            "--tx-in",
            faucet_txin,
            "--tx-out",
            f"{wallet.address}+{DEVNET_FUNDING_LOVELACE}",
            "--out-file",
            tx_body,
        ],
        include_network=True,
        include_socket=True,
    )
    cli.cardano_cli_conway(
        "transaction",
        "sign",
        [
            "--tx-body-file",
            tx_body,
            "--signing-key-file",
            faucet_skey,
            "--out-file",
            signed_tx,
        ],
    )
    tx_id = cli.cardano_cli_conway("transaction", "txid", ["--tx-file", signed_tx, "--output-text"])
    cli.cardano_cli_conway(
        "transaction",
        "submit",
        ["--tx-file", signed_tx],
        include_network=True,
        include_socket=True,
    )
    print(f"Submitted devnet funding transaction: {tx_id}")
    _wait_for_utxo(cli, wallet, temp_dir)


def start_devnet(node_version=DEFAULT_CARDANO_NODE_VERSION):
    cardano_home = get_cardano_home()
    network_dir = os.path.join(cardano_home, "devnet")
    keys_dir = os.environ.get("CARDANO_KEYS_DIR", os.path.join(cardano_home, "keys"))

    ensure_dir(keys_dir)
    _reset_devnet_state(network_dir, keys_dir)
    paths = prepare_node_dirs(cardano_home, "devnet")
    node_bin_dir = paths["node_bin_dir"]
    config_dir = paths["config_dir"]
    db_dir = paths["db_dir"]
    socket_path = paths["socket_path"]
    temp_dir = ensure_dir(os.path.join(keys_dir, "tmp"))

    _prepare_devnet_configs(config_dir)
    node_bin_path, cardano_cli_path = ensure_node_binaries(node_version, cardano_home, node_bin_dir)
    wallet_cli = CardanoCLI(
        network="devnet",
        executable=cardano_cli_path,
    )
    wallet = _ensure_wallet(wallet_cli, keys_dir)

    cmd = build_node_run_command(
        node_bin_path=node_bin_path,
        config_path=os.path.join(config_dir, "cardano-node.json"),
        db_dir=db_dir,
        socket_path=socket_path,
        topology_path=os.path.join(config_dir, "topology.json"),
        extra_args=[
            f"--shelley-kes-key={os.path.join(config_dir, 'kes.skey')}",
            f"--shelley-vrf-key={os.path.join(config_dir, 'vrf.skey')}",
            f"--shelley-operational-certificate={os.path.join(config_dir, 'opcert.cert')}",
            f"--byron-delegation-certificate={os.path.join(config_dir, 'byron-delegation.cert')}",
            f"--byron-signing-key={os.path.join(config_dir, 'byron-delegate.key')}",
        ],
    )
    print("Starting local Cardano devnet...")
    process = subprocess.Popen(cmd)

    try:
        _wait_for_socket(cardano_cli_path, socket_path, process)
        cli = CardanoCLI(
            network="devnet",
            executable=cardano_cli_path,
            socket_path=socket_path,
        )
        _fund_wallet(cli, wallet, config_dir, temp_dir)
        print(f"Devnet ready. Socket: {socket_path}")
        print(f"Default wallet: {wallet.address}")
        print(f"Funding target: {DEVNET_FUNDING_LOVELACE} lovelace")
        process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        process.wait()
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        raise
    finally:
        if process.poll() is None:
            process.wait()

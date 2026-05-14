#!/usr/bin/env python

import json
import os

# Import executor helper from exec module
from adaup.download.exec import executor

from adaup.download.node import DEFAULT_CARDANO_NODE_VERSION, download_and_setup_cardano_node
from adaup.download.hydra import download_and_setup_hydra
from adaup.download.mithril import download_and_setup_mithril
from adaup.download.etcd import download_and_setup_etcd
from adaup.download.node_config import download_network_configs, get_config_urls

def start(node_version=DEFAULT_CARDANO_NODE_VERSION, network="mainnet"):
    """
    Start the Cardano node.

    Args:
        node_version (str): The version of the Cardano node to use.
        network (str): The network to connect to (e.g., mainnet, testnet).
    """
    cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
    node_bin_dir = os.path.join(cardano_home, "bin")

    if not os.path.exists(node_bin_dir):
        os.makedirs(node_bin_dir)

    config_dir = os.path.join(cardano_home, network, "configuration")
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    os.makedirs(os.path.join(cardano_home, network, 'db'), exist_ok=True)

    # Download configs for the specified network
    download_network_configs(network, config_dir)

    config_path = os.path.join(config_dir, "config.json")
    required_node_version = node_version
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    min_node_version = config.get("MinNodeVersion")
    if min_node_version:
        requested_parts = tuple(int(part) for part in node_version.strip().lstrip("v").split("."))
        minimum_parts = tuple(int(part) for part in min_node_version.strip().lstrip("v").split("."))
        if requested_parts < minimum_parts:
            print(
                f"Requested cardano-node version {node_version} is older than the "
                f"network minimum {min_node_version}. Using {min_node_version} instead."
            )
            required_node_version = min_node_version

    node_bin_path = download_and_setup_cardano_node(
        required_node_version,
        cardano_home,
        node_bin_dir
    )

    # Start cardano-node
    print(f"Starting Cardano node on {network} network...")
    cmd = [
        node_bin_path, "run",
        f"--config={os.path.join(config_dir, 'config.json')}",
        f"--database-path={os.path.join(cardano_home, network, 'db')}",
        f"--socket-path={os.path.join(cardano_home, network, 'node.socket')}",
        f"--topology={os.path.join(config_dir, 'topology.json')}",
        "--port", "3001"
    ]
    [print(x) for x in cmd]
    # Replace the current process with the Cardano node command
    os.execv(cmd[0], cmd)

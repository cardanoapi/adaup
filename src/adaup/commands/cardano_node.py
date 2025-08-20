#!/usr/bin/env python

import os

# Import executor helper from exec module
from adaup.download.exec import executor

from adaup.download.node import download_and_setup_cardano_node
from adaup.download.hydra import download_and_setup_hydra
from adaup.download.mithril import download_and_setup_mithril
from adaup.download.etcd import download_and_setup_etcd
from adaup.download.node_config import download_network_configs, get_config_urls

def start(node_version="10.4.1", network="mainnet"):
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

    # Download and setup Cardano node only if cardano-node is missing
    from adaup.download.node import check_cardano_node_present

    # Check for cardano-node and cardano-cli before downloading
    if not check_cardano_node_present(node_bin_dir):
        print("Cardano binaries not found, proceeding with download...")
        node_bin_path = download_and_setup_cardano_node(node_version, cardano_home, node_bin_dir)
    else:
        node_bin_path = os.path.join(node_bin_dir, "cardano-node")
        print(f"Cardano node and cardano-cli already exist at {node_bin_dir}. Skipping download.")

    config_dir = os.path.join(cardano_home, network, "configuration")
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    os.makedirs(os.path.join(cardano_home, network, 'db'), exist_ok=True)

    # Download configs for the specified network
    download_network_configs(network, config_dir)

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

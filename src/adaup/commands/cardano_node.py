#!/usr/bin/env python

import os

from adaup.commands.devnet import start_devnet
from adaup.commands.node_support import (
    build_node_run_command,
    ensure_node_binaries,
    get_cardano_home,
    prepare_node_dirs,
    resolve_required_node_version,
)

from adaup.download.node import DEFAULT_CARDANO_NODE_VERSION
from adaup.download.exec import exec
from adaup.download.mithril import bootstrap_cardano_db_with_mithril, is_cardano_db_empty
from adaup.download.node_config import download_network_configs

def start(node_version=DEFAULT_CARDANO_NODE_VERSION, network="mainnet"):
    """
    Start the Cardano node.

    Args:
        node_version (str): The version of the Cardano node to use.
        network (str): The network to connect to (e.g., mainnet, testnet).
    """
    if network == "devnet":
        start_devnet(node_version)
        return

    cardano_home = get_cardano_home()
    paths = prepare_node_dirs(cardano_home, network)
    node_bin_dir = paths["node_bin_dir"]
    config_dir = paths["config_dir"]
    db_dir = paths["db_dir"]
    socket_path = paths["socket_path"]

    # Download configs for the specified network
    download_network_configs(network, config_dir)

    config_path = os.path.join(config_dir, "config.json")
    required_node_version = resolve_required_node_version(node_version, config_path)
    node_bin_path, _ = ensure_node_binaries(required_node_version, cardano_home, node_bin_dir)

    if os.environ.get("ADAUP_DISABLE_MITHRIL_BOOTSTRAP") == "1":
        print("Mithril bootstrap disabled by ADAUP_DISABLE_MITHRIL_BOOTSTRAP=1.")
    elif is_cardano_db_empty(db_dir):
        print(f"Database at {db_dir} is empty. Bootstrapping with Mithril for faster startup...")
        try:
            bootstrap_cardano_db_with_mithril(network, db_dir, node_bin_dir)
        except Exception as exc:
            print(f"Mithril bootstrap failed, continuing with normal sync: {exc}")
    else:
        print(f"Database at {db_dir} already has content. Skipping Mithril bootstrap.")

    # Start cardano-node
    print(f"Starting Cardano node on {network} network...")
    cmd = build_node_run_command(
        node_bin_path=node_bin_path,
        config_path=config_path,
        db_dir=db_dir,
        socket_path=socket_path,
        topology_path=os.path.join(config_dir, "topology.json"),
    )
    print("Executing:", " ".join(cmd))
    # Replace the current Python process with cardano-node for non-devnet networks.
    exec(cmd)

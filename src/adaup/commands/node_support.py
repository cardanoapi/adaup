#!/usr/bin/env python

import json
import os

from adaup.download.node import download_and_setup_cardano_node

DEFAULT_NODE_PORT = "3001"


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def get_cardano_home():
    return os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))


def prepare_node_dirs(cardano_home, network):
    node_bin_dir = ensure_dir(os.path.join(cardano_home, "bin"))
    network_dir = ensure_dir(os.path.join(cardano_home, network))
    config_dir = ensure_dir(os.path.join(network_dir, "configuration"))
    db_dir = ensure_dir(os.path.join(network_dir, "db"))
    socket_path = os.path.join(network_dir, "node.socket")

    return {
        "node_bin_dir": node_bin_dir,
        "network_dir": network_dir,
        "config_dir": config_dir,
        "db_dir": db_dir,
        "socket_path": socket_path,
    }


def resolve_required_node_version(node_version, config_path):
    required_node_version = node_version

    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    min_node_version = config.get("MinNodeVersion")
    if not min_node_version:
        return required_node_version

    requested_parts = tuple(int(part) for part in node_version.strip().lstrip("v").split("."))
    minimum_parts = tuple(int(part) for part in min_node_version.strip().lstrip("v").split("."))
    if requested_parts < minimum_parts:
        print(
            f"Requested cardano-node version {node_version} is older than the "
            f"network minimum {min_node_version}. Using {min_node_version} instead."
        )
        required_node_version = min_node_version

    return required_node_version


def ensure_node_binaries(node_version, cardano_home, node_bin_dir):
    node_bin_path = download_and_setup_cardano_node(node_version, cardano_home, node_bin_dir)
    cardano_cli_path = os.path.join(node_bin_dir, "cardano-cli")
    return node_bin_path, cardano_cli_path


def build_node_run_command(
    node_bin_path,
    config_path,
    db_dir,
    socket_path,
    topology_path,
    port=DEFAULT_NODE_PORT,
    extra_args=None,
):
    cmd = [
        node_bin_path,
        "run",
        f"--config={config_path}",
        f"--database-path={db_dir}",
        f"--socket-path={socket_path}",
        f"--topology={topology_path}",
        "--port",
        port,
    ]

    if extra_args:
        cmd.extend(extra_args)

    return cmd

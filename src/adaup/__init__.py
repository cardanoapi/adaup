#!/usr/bin/env python

import os
import sys
import argparse

from .commands.cardano_cli import CardanoCLI
from .download.exec import executor, exec
from .commands.hydra import (
    run_hydra_tui,
    bootstrap_hydra_nodes,
    run_hydra_node,
    prune_hydra_directories,
    reset_hydra_data
)

def main():
    parser = argparse.ArgumentParser(description="Cardano node, CLI and module management")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Node command
    parser_node = subparsers.add_parser("node", help="Start a Cardano node")
    parser_node.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network to run the node on (default: mainnet)"
    )
    parser_node.add_argument(
        "--version",
        default="10.5.1",
        help="Cardano node version to use"
    )

    # Mithril command
    parser_mithril = subparsers.add_parser("mithril", help="Download and setup Mithril")
    parser_mithril.add_argument(
        "--version",
        default="0.2.5",  # Example default version
        help="Mithril client version to use"
    )

    # Hydra command
    parser_hydra = subparsers.add_parser("hydra", help="Manage Cardano hydra nodes")
    hydra_subparsers = parser_hydra.add_subparsers(dest="subcommand", help="Hydra subcommands")

    # Node subcommand
    parser_hydra_node = hydra_subparsers.add_parser("node", help="Start a hydra node")
    parser_hydra_node.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network to run the hydra node on (default: mainnet)"
    )
    parser_hydra_node.add_argument(
        "index",
        nargs="?",
        default=0,
        type=int,
        help="The index of the hydra node to run"
    )
    parser_hydra_node.add_argument(
        "--version",
        default="0.22.4",  # Example default version
        help="Hydra client version to use"
    )

    # TUI subcommand
    parser_hydra_tui = hydra_subparsers.add_parser("tui", help="Open the hydra-tui interface")
    parser_hydra_tui.add_argument(
        "index",
        nargs="?",
        default=0,
        type=int,
        help="The index of the node for which to open tui"
    )

    # Bootstrap subcommand
    parser_hydra_bootstrap = hydra_subparsers.add_parser("bootstrap", help="Generate required folders and credentials for hydra nodes")
    parser_hydra_bootstrap.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network for which to generate hydra node credentials (default: mainnet)"
    )
    parser_hydra_bootstrap.add_argument(
        "no_of_nodes",
        type=int,
        default=1,
        help="The number of hydra nodes for which to generate credentials"
    )

    # Prune subcommand
    parser_hydra_prune = hydra_subparsers.add_parser("prune", help="Remove all hydra-xxx directories for a given network")
    parser_hydra_prune.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network for which to prune hydra node directories (default: mainnet)"
    )

    # Reset subcommand
    parser_hydra_reset = hydra_subparsers.add_parser("reset", help="Delete hydra data and re-query protocol parameters")
    parser_hydra_reset.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network for which to reset hydra node data (default: mainnet)"
    )

    # Etcd command
    parser_etcd = subparsers.add_parser("etcd", help="Download and setup Etcd")
    parser_etcd.add_argument(
        "--version",
        default="v3.5.21",  # Example default version
        help="Etcd client version to use"
    )

    # CLI command
    parser_cli = subparsers.add_parser("cli", help="Run cardano-cli")
    # We don't add arguments here for cardano-cli as they will be passed directly
    # This parser is just to register the 'cli' command.

    # Parse only the known commands first
    # This allows us to handle 'cli' command's arguments separately
    known_args, unknown_args = parser.parse_known_args()

    if known_args.command == "node":
        from .commands.cardano_node import start
        start(known_args.version, known_args.network)
    elif known_args.command == "cli":
        from adaup.commands.cardano_cli import run
        # Pass all remaining arguments directly to cardano-cli
        run(unknown_args)
    elif known_args.command == "mithril":
        from .download.mithril import download_and_setup_mithril, run_mithril_client
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        node_bin_dir = os.path.join(cardano_home, "bin")
        if not os.path.exists(node_bin_dir):
            os.makedirs(node_bin_dir)
        download_and_setup_mithril(node_bin_dir)
        run_mithril_client(node_bin_dir)
    elif known_args.command == "hydra":
        if known_args.subcommand == "tui":
            run_hydra_tui(known_args)
        elif known_args.subcommand == "bootstrap":
            bootstrap_hydra_nodes(known_args)
        elif known_args.subcommand == "node":
            run_hydra_node(known_args)
        elif known_args.subcommand == "prune":
            prune_hydra_directories(known_args)
        elif known_args.subcommand == "reset":
            reset_hydra_data(known_args)
        else:
            parser.print_help()
    elif known_args.command == "etcd":
        from .download.etcd import download_and_setup_etcd, run_etcd
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        node_bin_dir = os.path.join(cardano_home, "bin")
        if not os.path.exists(node_bin_dir):
            os.makedirs(node_bin_dir)
        download_and_setup_etcd(known_args.version, node_bin_dir)
        run_etcd(node_bin_dir)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

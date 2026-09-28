#!/usr/bin/env python

import os
import sys
import argparse

from .commands.cardano_cli import CardanoCLI
from .download.exec import executor, exec
from .download.node import DEFAULT_CARDANO_NODE_VERSION
from .download.mithril import DEFAULT_MITHRIL_DISTRIBUTION
from .commands.hydra import (
    HYDRA_VERSION,
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
        default=DEFAULT_CARDANO_NODE_VERSION,
        help="Cardano node version to use"
    )

    # Mithril command
    parser_mithril = subparsers.add_parser("mithril", help="Download and setup Mithril")
    parser_mithril.add_argument(
        "--version",
        default=DEFAULT_MITHRIL_DISTRIBUTION,
        help="Mithril client distribution to use"
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
        default=HYDRA_VERSION,
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
    parser_hydra_bootstrap.add_argument(
        "--version",
        default=HYDRA_VERSION,
        help="Hydra client version to use"
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

    # Devnet command
    parser_devnet = subparsers.add_parser(
        "devnet",
        help="Run a local devnet (use --docker for the docker stack with kuber and db-sync)",
        description=(
            "Run a local Conway devnet. With --docker the node, kuber, db-sync, postgres and an "
            "anchor file server run in docker; most options can also be set through the "
            "ADAUP_DEVNET_* environment variable of the same name."
        ),
    )
    parser_devnet.add_argument(
        "action",
        nargs="?",
        default="up",
        choices=["up", "down", "status", "smoke"],
        help="up (default): start a fresh devnet; down: remove it; status: show it; smoke: run the governance smoke test",
    )
    parser_devnet.add_argument("--docker", action="store_true", help="Run the devnet in docker")
    parser_devnet.add_argument("--dir", default=None, help="Devnet output directory (default: ~/.cardano/devnet-docker)")
    parser_devnet.add_argument("--slot-length", type=float, default=None, help="Slot length in seconds (default 0.2)")
    parser_devnet.add_argument("--epoch-length", type=int, default=None, help="Epoch length in slots (default 300)")
    parser_devnet.add_argument("--active-slots-coeff", type=float, default=None, help="Active slots coefficient (default 0.25)")
    parser_devnet.add_argument("--security-param", type=int, default=None, help="Security parameter k (default 10)")
    parser_devnet.add_argument("--gov-action-lifetime", type=int, default=None,
                               help="Governance action lifetime in epochs (default: about 2h of wall-clock time)")
    parser_devnet.add_argument("--drep-activity", type=int, default=None,
                               help="DRep activity in epochs (default: about 2h of wall-clock time)")
    parser_devnet.add_argument("--no-kuber", dest="kuber", action="store_const", const=False, default=None,
                               help="Do not start kuber")
    parser_devnet.add_argument("--no-dbsync", dest="dbsync", action="store_const", const=False, default=None,
                               help="Do not start db-sync and postgres")
    parser_devnet.add_argument("-d", "--detach", action="store_true",
                               help="Return once the node produces blocks instead of following the logs")
    parser_devnet.add_argument("--wait", action="store_true", help="Also wait until kuber and db-sync are healthy")
    parser_devnet.add_argument("--actions", default=None,
                               help="smoke: comma separated proposals to create (default: all of "
                                    "info,treasury,parameter,hardfork,no-confidence,committee,constitution)")
    parser_devnet.add_argument("--ratify", default=None,
                               help="smoke: proposals that get enough yes votes to be enacted "
                                    "(default: treasury,parameter,committee,constitution)")
    parser_devnet.add_argument("--no-wait-enactment", dest="wait_enactment", action="store_false",
                               help="smoke: return after voting instead of waiting for enactment")

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
    elif known_args.command == "devnet":
        run_devnet(known_args, parser_devnet)
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
        download_and_setup_mithril(node_bin_dir, known_args.version)
        run_mithril_client(node_bin_dir, known_args.version)
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
    else:
        parser.print_help()

def run_devnet(args, parser):
    if not args.docker:
        if args.action != "up":
            parser.error(f"'{args.action}' is only available for the docker devnet (add --docker)")
        from .commands.devnet import start_devnet
        start_devnet()
        return

    from .commands import devnet_docker
    overrides = {
        name: getattr(args, name)
        for name in (
            "dir", "slot_length", "epoch_length", "active_slots_coeff", "security_param",
            "gov_action_lifetime", "drep_activity", "kuber", "dbsync",
        )
    }
    try:
        settings = devnet_docker.load_settings(overrides)
    except ValueError as error:
        parser.error(str(error))

    if args.action != "up":
        settings = devnet_docker.load_saved_settings(settings)

    try:
        if args.action == "up":
            devnet_docker.devnet_up(settings, detach=args.detach, wait=args.wait)
        elif args.action == "down":
            devnet_docker.devnet_down(settings)
        elif args.action == "status":
            devnet_docker.devnet_status(settings)
        elif args.action == "smoke":
            from .commands.devnet_smoke import run_smoke
            run_smoke(settings, actions=args.actions, ratify=args.ratify, wait_enactment=args.wait_enactment)
    except RuntimeError as error:
        print(f"Error: {error}")
        sys.exit(1)

if __name__ == "__main__":
    main()

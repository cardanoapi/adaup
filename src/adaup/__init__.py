#!/usr/bin/env python

import os
import sys
import argparse

from .commands.cardano_cli import CardanoCLI
from .download.exec import executor,exec

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

    # Hydra command with subcommands for node and tui
    parser_hydra = subparsers.add_parser("hydra", help="Manage Cardano hydra nodes")
    hydra_subparsers = parser_hydra.add_subparsers(dest="subcommand", help="Hydra subcommands")

    # Node subcommand
    parser_node = hydra_subparsers.add_parser("node", help="Start a hydra node")
    parser_node.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network to run the hydra node on (default: mainnet)"
    )
    parser_node.add_argument(
        "index",
        nargs="?",
        default=0,
        type=int,
        help="The index of the hydra node to run"
    )
    parser_node.add_argument(
        "--version",
        default="0.22.0",  # Example default version
        help="Hydra client version to use"
    )

    # TUI subcommand
    parser_tui = hydra_subparsers.add_parser("tui", help="Open the hydra-tui interface")
    parser_tui.add_argument(
        "index",
        nargs="?",
        default=0,
        type=int,
        help="The index of the node for which to open tui"
    )

    # Bootstrap subcommand
    parser_bootstrap = hydra_subparsers.add_parser("bootstrap", help="Generate required folders and credentials for hydra nodes")
    parser_bootstrap.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network for which to generate hydra node credentials (default: mainnet)"
    )
    parser_bootstrap.add_argument(
        "no_of_nodes",
        type=int,
        default=1,
        help="The number of hydra nodes for which to generate credentials"
    )

    # Prune subcommand
    parser_prune = hydra_subparsers.add_parser("prune", help="Remove all hydra-xxx directories for a given network")
    parser_prune.add_argument(
        "network",
        nargs="?",
        default="mainnet",
        help="The network for which to prune hydra node directories (default: mainnet)"
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
    parser_cli.add_argument("cli_args", nargs=argparse.REMAINDER, help="Arguments to pass to cardano-cli")

    args = parser.parse_args()

    if args.command == "node":
        from .commands.cardano_node import start
        start(args.version, args.network)
    elif args.command == "cli":
        from .commands.cardano_cli import run
        run(args.cli_args)
    elif args.command == "mithril":
        from .download.mithril import download_and_setup_mithril, run_mithril_client
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        node_bin_dir = os.path.join(cardano_home, "bin")
        if not os.path.exists(node_bin_dir):
            os.makedirs(node_bin_dir)
        download_and_setup_mithril(node_bin_dir)
        run_mithril_client(node_bin_dir)
    elif args.command == "hydra" and args.subcommand == "tui":
        # Handle the hydra tui command
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        network = "preview"  # Default network for TUI since it's not specified in this subcommand
        node_bin_dir = os.path.join(cardano_home, "bin")
        credentials_dir = os.path.join(
            cardano_home,
            network,
            f"hydra-{args.index}",
            "credentials"
        )

        # Check if the hydra-tui executable exists
        hydra_tui_path = os.path.join(node_bin_dir, "hydra-tui")
        if not os.path.isfile(hydra_tui_path) or not os.access(hydra_tui_path, os.X_OK):
            print(f"Error: 'hydra-tui' executable not found in {node_bin_dir}")
            sys.exit(1)

        # Find the funds signing key for this node
        funds_key = None
        for filename in os.listdir(credentials_dir):
            if filename.endswith(".sk") and "funds" in filename:
                funds_key = os.path.join(credentials_dir, filename)
                break

        if not funds_key or not os.path.isfile(funds_key):
            print(f"Error: Could not find a 'funds' signing key in {credentials_dir}")
            sys.exit(1)

        # Execute hydra-tui with the appropriate signing key
        cmd = [hydra_tui_path, "-k", funds_key]
        exec(cmd)
    elif args.command == "hydra" and args.subcommand == "bootstrap":
        from .download.hydra import (
            create_hydra_credentials,
            generate_protocol_parameters,
            fetch_network_json,
            download_and_setup_hydra, # Ensure hydra-node is downloaded
            generate_and_save_hydra_run_script # New function
        )
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        node_bin_dir = os.path.join(cardano_home, "bin")

        # Ensure hydra-node is downloaded and executable
        download_and_setup_hydra("0.22.0", node_bin_dir) # Use a default version for bootstrap

        networks_data = fetch_network_json()
        node_version = "0.22.0" # Assuming this is the version for hydra-node
        tx_id_list = networks_data.get(args.network, {}).get(node_version, [])
        if not isinstance(tx_id_list, str):
            print(f"Error: Could not find transaction ID for {args.network}.{node_version} in the network configuration.")
            sys.exit(1)
        tx_id = tx_id_list
        testnet_magic = 2 if args.network != "mainnet" else 0
        hydra_node_path = os.path.join(node_bin_dir, "hydra-node")

        node_configs = [] # To store paths to credentials for each node

        # First pass: Generate all credentials and store their paths
        for i in range(args.no_of_nodes):
            print(f"Generating credentials for hydra node {i} on network {args.network}...")
            cli = CardanoCLI(network=args.network,
                             executable=os.path.join(node_bin_dir, "cardano-cli"),
                             socket_path=os.path.join(cardano_home, args.network, "node.socket"))

            hydra_dir = os.path.join(cardano_home, args.network, f"hydra-{i}")
            credentials_dir = os.path.join(hydra_dir, "credentials")
            data_dir = os.path.join(hydra_dir, "data")

            os.makedirs(credentials_dir, exist_ok=True)
            os.makedirs(data_dir, exist_ok=True)

            create_hydra_credentials(cli, credentials_dir)
            protocol_params_path = generate_protocol_parameters(cli, os.path.join(credentials_dir, "protocol-params.json"))

            node_configs.append({
                "index": i,
                "hydra_dir": hydra_dir,
                "credentials_dir": credentials_dir,
                "data_dir": data_dir,
                "cardano_signing_key": os.path.join(credentials_dir, "node.sk"),
                "hydra_signing_key": os.path.join(credentials_dir, "hydra.sk"),
                "cardano_verification_key": os.path.join(credentials_dir, "node.vk"),
                "hydra_verification_key": os.path.join(credentials_dir, "hydra.vk"),
                "protocol_params_path": protocol_params_path
            })
        print(f"Successfully generated credentials for {args.no_of_nodes} hydra nodes on network {args.network}.")

        # Second pass: Generate run.sh scripts with full peer information
        for config in node_configs:
            generate_and_save_hydra_run_script(
                node_index=config['index'],
                network=args.network,
                cardano_home=cardano_home,
                node_bin_dir=node_bin_dir,
                tx_id=tx_id,
                testnet_magic=testnet_magic,
                hydra_node_path=hydra_node_path,
                node_configs=node_configs # Pass all configs for peer discovery
            )

        print(f"All run scripts generated with correct peer configurations for {args.no_of_nodes} hydra nodes on network {args.network}.")
    elif args.command == "hydra" and args.subcommand == "node":
        from .download.hydra import (
            download_and_setup_hydra,
            create_hydra_credentials,
            generate_protocol_parameters,
            fetch_network_json,
            generate_and_save_hydra_run_script # New function
        )
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        node_bin_dir = os.path.join(cardano_home, "bin")
        network = args.network if args.network else "preview"
        node_index = args.index

        hydra_dir = os.path.join(cardano_home, network, f"hydra-{node_index}")
        run_script_path = os.path.join(hydra_dir, "run.sh")

        if os.path.exists(run_script_path) and os.access(run_script_path, os.X_OK):
            print(f"Executing existing run.sh for hydra node {node_index} on network {network}...")
            exec([run_script_path])
        else:
            print(f"run.sh not found or not executable for node {node_index}. Generating and executing...")
            
            # Ensure hydra-node is downloaded and executable
            download_and_setup_hydra("0.22.0", node_bin_dir)

            cli = CardanoCLI(network=network,
                             executable=os.path.join(node_bin_dir, "cardano-cli"),
                             socket_path=os.path.join(cardano_home, network, "node.socket"))

            credentials_dir = os.path.join(hydra_dir, "credentials")
            data_dir = os.path.join(hydra_dir, "data")

            os.makedirs(credentials_dir, exist_ok=True)
            os.makedirs(data_dir, exist_ok=True)

            create_hydra_credentials(cli, credentials_dir)
            generate_protocol_parameters(cli, os.path.join(credentials_dir, "protocol-params.json"))

            networks_data = fetch_network_json()
            node_version = "0.22.0"
            tx_id_list = networks_data.get(network, {}).get(node_version, [])
            if not isinstance(tx_id_list, str):
                print(f"Error: Could not find transaction ID for {network}.{node_version} in the network configuration.")
                sys.exit(1)
            tx_id = tx_id_list
            testnet_magic = 2 if network != "mainnet" else 0
            hydra_node_path = os.path.join(node_bin_dir, "hydra-node")

            # Gather existing node configs for peer discovery
            existing_node_configs = []
            network_dir = os.path.join(cardano_home, network)
            if os.path.exists(network_dir):
                for item in os.listdir(network_dir):
                    if item.startswith("hydra-") and os.path.isdir(os.path.join(network_dir, item)):
                        try:
                            peer_index = int(item.split('-')[1])
                            peer_hydra_dir = os.path.join(network_dir, item)
                            peer_credentials_dir = os.path.join(peer_hydra_dir, "credentials")
                            
                            # Only add if credentials exist
                            if os.path.exists(os.path.join(peer_credentials_dir, "node.vk")) and \
                               os.path.exists(os.path.join(peer_credentials_dir, "hydra.vk")) and \
                               os.path.exists(os.path.join(peer_credentials_dir, "node.sk")) and \
                               os.path.exists(os.path.join(peer_credentials_dir, "hydra.sk")) and \
                               os.path.exists(os.path.join(peer_credentials_dir, "protocol-params.json")):
                                existing_node_configs.append({
                                    "index": peer_index,
                                    "hydra_dir": peer_hydra_dir,
                                    "credentials_dir": peer_credentials_dir,
                                    "data_dir": os.path.join(peer_hydra_dir, "data"),
                                    "cardano_signing_key": os.path.join(peer_credentials_dir, "node.sk"),
                                    "hydra_signing_key": os.path.join(peer_credentials_dir, "hydra.sk"),
                                    "cardano_verification_key": os.path.join(peer_credentials_dir, "node.vk"),
                                    "hydra_verification_key": os.path.join(peer_credentials_dir, "hydra.vk"),
                                    "protocol_params_path": os.path.join(peer_credentials_dir, "protocol-params.json")
                                })
                        except ValueError:
                            pass # Ignore directories not matching hydra-X pattern
            
            # Add the current node's config to the list for peer discovery
            current_node_config = {
                "index": node_index,
                "hydra_dir": hydra_dir,
                "credentials_dir": credentials_dir,
                "data_dir": data_dir,
                "cardano_signing_key": cardano_signing_key,
                "hydra_signing_key": hydra_signing_key,
                "cardano_verification_key": os.path.join(credentials_dir, "node.vk"),
                "hydra_verification_key": os.path.join(credentials_dir, "hydra.vk"),
                "protocol_params_path": protocol_params_path
            }
            # Ensure current node is in the list, if not already (e.g., if it was just created)
            if not any(d['index'] == node_index for d in existing_node_configs):
                existing_node_configs.append(current_node_config)
            
            # Generate and save the run script
            if generate_and_save_hydra_run_script(
                node_index=node_index,
                network=network,
                cardano_home=cardano_home,
                node_bin_dir=node_bin_dir,
                tx_id=tx_id,
                testnet_magic=testnet_magic,
                hydra_node_path=hydra_node_path,
                node_configs=existing_node_configs # Pass all existing configs for peer discovery
            ):
                exec([run_script_path]) # Execute the newly created script
            else:
                print(f"Failed to generate run.sh for node {node_index}. Cannot execute.")
                sys.exit(1)
    elif args.command == "hydra" and args.subcommand == "prune":
        import shutil
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        network_dir = os.path.join(cardano_home, args.network)
        
        if not os.path.exists(network_dir):
            print(f"Error: Network directory '{network_dir}' does not exist.")
            sys.exit(1)

        pruned_count = 0
        for item in os.listdir(network_dir):
            if item.startswith("hydra-") and os.path.isdir(os.path.join(network_dir, item)):
                hydra_dir_to_remove = os.path.join(network_dir, item)
                print(f"Removing directory: {hydra_dir_to_remove}")
                shutil.rmtree(hydra_dir_to_remove)
                pruned_count += 1
        
        if pruned_count > 0:
            print(f"Successfully pruned {pruned_count} hydra directories for network {args.network}.")
        else:
            print(f"No hydra directories found to prune for network {args.network}.")
    elif args.command == "etcd":
        from .download.etcd import download_and_setup_etcd, run_etcd
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        node_bin_dir = os.path.join(cardano_home, "bin")
        if not os.path.exists(node_bin_dir):
            os.makedirs(node_bin_dir)
        download_and_setup_etcd(args.version, node_bin_dir)
        run_etcd(node_bin_dir)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

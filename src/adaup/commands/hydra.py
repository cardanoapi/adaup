import os
import shutil
import glob
import json
import argparse
import sys

from adaup.commands.cardano_cli import CardanoCLI, WalletStore
from adaup.download.hydra import (
    fetch_network_json,
    download_and_setup_hydra
)
from adaup.download.exec import executor, exec

HOME = os.environ.get("HOME", "/root")
HYDRA_VERSION="0.22.4"

def create_hydra_credentials(cli:CardanoCLI,credentials_dir):
    """
    Create the necessary credentials for a Hydra node.

    Args:
        credentials_dir (str): The directory where the credentials will be stored.
    """
    print(f"Creating hydra credentials in {credentials_dir}...")

    cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
    cardano_cli_path = os.path.join(cardano_home, "bin", "cardano-cli")

    if not os.path.isfile(cardano_cli_path) or not os.access(cardano_cli_path, os.X_OK):
        print(f"Error: cardano-cli executable not found at {cardano_cli_path}")
        sys.exit(1)

    store = WalletStore(credentials_dir)
    if store.gen_enterprise_wallet(cli,"node",skip_if_present=True) ==False:
        print("[Hydra] Node keys are already present")

    if store.gen_enterprise_wallet(cli,"funds",skip_if_present=True) == False:
        print("[Hydra] funds keys are already present")
   
    hydr_output_file=os.path.join(credentials_dir, "hydra")
    files=[hydr_output_file+".sk",hydr_output_file+".vk"]
    
    present =False
    for file in files:
        if  os.path.isfile(file) and os.access(file, os.X_OK):
            present=True
    if present:
        print("[Hydra] Node keys are already present")
        return
        
    hydra_node_path = os.path.join(cardano_home, "bin", "hydra-node")
    if not os.path.isfile(hydra_node_path) or not os.access(hydra_node_path, os.X_OK):
        print(f"Error: hydra-node executable not found at {hydra_node_path}")
        sys.exit(1)

    executor([
        hydra_node_path, "gen-hydra-key",
        "--output-file", hydr_output_file
    ], show_command=True, throw_error=True)
    print("Hydra credentials created successfully.")

def generate_protocol_parameters(cli:CardanoCLI,filePath:str):
    """
    Generate protocol parameters for the hydra node.

    Args:
        node_bin_dir (str): The directory where cardano-cli is located.

    Returns:
        str: Path to the generated protocol parameters file.
    """
    print("Generating ledger protocol parameters...")

    result = cli.cardano_cli("query","protocol-parameters",[],include_network=True,include_socket=True)
    params = json.loads(result)

    params['txFeeFixed'] = 0
    params['txFeePerByte'] = 0
    params['executionUnitPrices']['priceMemory'] = 0
    params['executionUnitPrices']['priceSteps'] = 0

    with open(filePath, 'w') as f:
        json.dump(params, f, indent=2)
    return filePath

def generate_and_save_hydra_run_script(
        node_index: int,
        network: str,
        cardano_home: str,
        node_bin_dir: str,
        tx_id: str,
        testnet_magic: int,
        hydra_node_path: str,
        node_configs: list = None
    ):
    """
    Generates the run.sh script for a specific Hydra node.

    Args:
        node_index (int): The index of the current hydra node.
        network (str): The Cardano network.
        cardano_home (str): Path to the .cardano home directory.
        node_bin_dir (str): Path to the directory containing hydra-node executable.
        tx_id (str): Hydra scripts transaction ID.
        testnet_magic (int): Testnet magic number.
        hydra_node_path (str): Path to the hydra-node executable.
        node_configs (list): A list of dictionaries, where each dictionary contains
                             configuration details (including paths to verification keys)
                             for all hydra nodes in the network. Used for peer discovery.
    """
    print(f"Generating run.sh script for hydra node {node_index} on network {network}...")

    hydra_dir = os.path.join(cardano_home, network, f"hydra-{node_index}")
    credentials_dir = os.path.join(hydra_dir, "credentials")
    data_dir = os.path.join(hydra_dir, "data")

    os.makedirs(credentials_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    cardano_signing_key = os.path.join(credentials_dir, "node.sk")
    hydra_signing_key = os.path.join(credentials_dir, "hydra.sk")
    protocol_params_path = os.path.join(credentials_dir, "protocol-params.json")

    if not os.path.exists(cardano_signing_key):
        print(f"Error: Cardano signing key not found at {cardano_signing_key}")
        return False
    if not os.path.exists(hydra_signing_key):
        print(f"Error: Hydra signing key not found at {hydra_signing_key}")
        return False
    if not os.path.exists(protocol_params_path):
        print(f"Error: Protocol parameters not found at {protocol_params_path}")
        return False

    run_command = [
        hydra_node_path,
        "--node-id", f"node-{network}-{node_index}",
        "--persistence-dir", data_dir,
        "--cardano-signing-key", cardano_signing_key,
        "--hydra-signing-key", hydra_signing_key,
        "--hydra-scripts-tx-id", tx_id,
        "--ledger-protocol-parameters", protocol_params_path,
        "--testnet-magic", str(testnet_magic),
        "--node-socket", os.path.join(cardano_home, network, "node.socket"),
        "--api-port", str(4001 + node_index),
        "--listen", f"127.0.0.1:{5001 + node_index}",
        "--api-host", "0.0.0.0",
    ]

    peers = []
    if node_configs:
        for other_config in node_configs:
            if other_config['index'] != node_index:
                peer_vk_path = other_config['cardano_verification_key']
                hydra_vk_path = other_config['hydra_verification_key']
                if os.path.exists(peer_vk_path) and os.path.exists(hydra_vk_path):
                    peers.append(f"--peer=127.0.0.1:{5001 + other_config['index']}")
                    peers.append(f"--cardano-verification-key={peer_vk_path}")
                    peers.append(f"--hydra-verification-key={hydra_vk_path}")
                else:
                    print(f"Warning: Missing keys for potential peer {other_config['index']}. Skipping peer configuration for node {node_index}.")
    run_command.extend(peers)

    formatted_command_parts = []
    cmd_idx = 1
    while cmd_idx < len(run_command):
        part = str(run_command[cmd_idx])
        if part.startswith("--"):
            if cmd_idx + 1 < len(run_command) and not str(run_command[cmd_idx+1]).startswith("--"):
                formatted_command_parts.append(f"  {part} {str(run_command[cmd_idx+1])}")
                cmd_idx += 2
            else:
                formatted_command_parts.append(f"  {part}")
                cmd_idx += 1
        else:
            formatted_command_parts.append(f"  {part}")
            cmd_idx += 1
    
    run_script_content = f"#!/bin/bash\n\n{run_command[0]}"
    if len(formatted_command_parts) > 0:
        run_script_content += " \\\n" + " \\\n".join(formatted_command_parts)
    run_script_content += "\n"
    
    run_script_path = os.path.join(hydra_dir, "run.sh")

    with open(run_script_path, 'w') as f:
        f.write(run_script_content)
    os.chmod(run_script_path, 0o755)

    print(f"Created run.sh for node {node_index} at {run_script_path}")
    return True

def reset_hydra_data(args):
    """
    Deletes all contents of hydra-{n}/data/** and re-queries protocol parameters.
    """
    network_name = args.network
    print(f"Resetting Hydra data for network: {network_name}")

    cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
    node_bin_dir = os.path.join(cardano_home, "bin")
    cli = CardanoCLI(network=network_name,
                     executable=os.path.join(node_bin_dir, "cardano-cli"),
                     socket_path=os.path.join(cardano_home, network_name, "node.socket"))

    network_dir = os.path.join(cardano_home, network_name)

    hydra_dirs = glob.glob(os.path.join(network_dir, "hydra-*"))

    if not hydra_dirs:
        print(f"No hydra-* directories found for network {network_name}. Nothing to reset.")
        return

    for hydra_dir in hydra_dirs:
        node_index = os.path.basename(hydra_dir).split('-')[-1]
        data_dir = os.path.join(hydra_dir, "data")
        credentials_dir = os.path.join(hydra_dir, "credentials")
        protocol_params_file = os.path.join(credentials_dir, "protocol-params.json")

        # Delete contents of data directory
        if os.path.exists(data_dir):
            print(f"Deleting contents of {data_dir}...")
            for item in os.listdir(data_dir):
                item_path = os.path.join(data_dir, item)
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            print(f"Contents of {data_dir} deleted.")
        else:
            print(f"Data directory {data_dir} does not exist. Skipping deletion.")

        # Re-query and update protocol parameters
        if os.path.exists(credentials_dir):
            print(f"Re-querying and updating protocol parameters for {hydra_dir}...")
            generate_protocol_parameters(cli, protocol_params_file)
            print(f"Protocol parameters updated in {protocol_params_file}.")
        else:
            print(f"Credentials directory {credentials_dir} does not exist. Skipping protocol parameter update.")

    print(f"Hydra reset complete for network {network_name}.")

def run_hydra_tui(args):
    cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
    node_bin_dir = os.path.join(cardano_home, "bin")
    network = "preview"  # Default network for TUI since it's not specified in this subcommand
    credentials_dir = os.path.join(
        cardano_home,
        network,
        f"hydra-{args.index}",
        "credentials"
    )

    hydra_tui_path = os.path.join(node_bin_dir, "hydra-tui")
    if not os.path.isfile(hydra_tui_path) or not os.access(hydra_tui_path, os.X_OK):
        print(f"Error: 'hydra-tui' executable not found in {node_bin_dir}")
        sys.exit(1)

    funds_key = None
    for filename in os.listdir(credentials_dir):
        if filename.endswith(".sk") and "funds" in filename:
            funds_key = os.path.join(credentials_dir, filename)
            break

    if not funds_key or not os.path.isfile(funds_key):
        print(f"Error: Could not find a 'funds' signing key in {credentials_dir}")
        sys.exit(1)

    cmd = [hydra_tui_path, "-k", funds_key]
    exec(cmd)

def bootstrap_hydra_nodes(args):
    cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
    node_bin_dir = os.path.join(cardano_home, "bin")

    download_and_setup_hydra(HYDRA_VERSION, node_bin_dir)

    networks_data = fetch_network_json()
    node_version = HYDRA_VERSION
    tx_id_list = networks_data.get(args.network, {}).get(node_version, [])
    if not isinstance(tx_id_list, str):
        print(f"Error: Could not find transaction ID for {args.network}.{node_version} in the network configuration.")
        sys.exit(1)
    tx_id = tx_id_list
    testnet_magic = 2 if args.network != "mainnet" else 0
    hydra_node_path = os.path.join(node_bin_dir, "hydra-node")

    node_configs = []
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

    for config in node_configs:
        generate_and_save_hydra_run_script(
            node_index=config['index'],
            network=args.network,
            cardano_home=cardano_home,
            node_bin_dir=node_bin_dir,
            tx_id=tx_id,
            testnet_magic=testnet_magic,
            hydra_node_path=hydra_node_path,
            node_configs=node_configs
        )

    print(f"All run scripts generated with correct peer configurations for {args.no_of_nodes} hydra nodes on network {args.network}.")

def run_hydra_node(args):
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
        
        download_and_setup_hydra(HYDRA_VERSION, node_bin_dir)

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
        node_version = HYDRA_VERSION
        tx_id_list = networks_data.get(network, {}).get(node_version, [])
        if not isinstance(tx_id_list, str):
            print(f"Error: Could not find transaction ID for {network}.{node_version} in the network configuration.")
            sys.exit(1)
        tx_id = tx_id_list
        testnet_magic = 2 if network != "mainnet" else 0
        hydra_node_path = os.path.join(node_bin_dir, "hydra-node")

        existing_node_configs = []
        network_dir = os.path.join(cardano_home, network)
        if os.path.exists(network_dir):
            for item in os.listdir(network_dir):
                if item.startswith("hydra-") and os.path.isdir(os.path.join(network_dir, item)):
                    try:
                        peer_index = int(item.split('-')[1])
                        peer_hydra_dir = os.path.join(network_dir, item)
                        peer_credentials_dir = os.path.join(peer_hydra_dir, "credentials")
                        
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
                        pass
        
        current_node_config = {
            "index": node_index,
            "hydra_dir": hydra_dir,
            "credentials_dir": credentials_dir,
            "data_dir": data_dir,
            "cardano_signing_key": os.path.join(credentials_dir, "node.sk"),
            "hydra_signing_key": os.path.join(credentials_dir, "hydra.sk"),
            "cardano_verification_key": os.path.join(credentials_dir, "node.vk"),
            "hydra_verification_key": os.path.join(credentials_dir, "hydra.vk"),
            "protocol_params_path": os.path.join(credentials_dir, "protocol-params.json")
        }
        if not any(d['index'] == node_index for d in existing_node_configs):
            existing_node_configs.append(current_node_config)
        
        if generate_and_save_hydra_run_script(
            node_index=node_index,
            network=network,
            cardano_home=cardano_home,
            node_bin_dir=node_bin_dir,
            tx_id=tx_id,
            testnet_magic=testnet_magic,
            hydra_node_path=hydra_node_path,
            node_configs=existing_node_configs
        ):
            exec([run_script_path])
        else:
            print(f"Failed to generate run.sh for node {node_index}. Cannot execute.")
            sys.exit(1)

def prune_hydra_directories(args):
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

def run(args):
    """
    Entry point for hydra commands.
    """
    if args.subcommand == "tui":
        run_hydra_tui(args)
    elif args.subcommand == "bootstrap":
        bootstrap_hydra_nodes(args)
    elif args.subcommand == "node":
        run_hydra_node(args)
    elif args.subcommand == "prune":
        prune_hydra_directories(args)
    elif args.subcommand == "reset":
        reset_hydra_data(args)
    else:
        print(f"Unknown hydra subcommand: {args.subcommand}")
        sys.exit(1)

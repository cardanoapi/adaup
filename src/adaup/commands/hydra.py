import os
import shutil
import glob
import json
import argparse
import subprocess
import sys
import time
from typing import List

from adaup.commands.cardano_cli import CardanoCLI, WalletStore, parse_network
from adaup.download.hydra import (
    fetch_network_json,
    download_and_setup_hydra
)
from adaup.download.exec import executor, exec

HOME = os.environ.get("HOME", "/root")
HYDRA_VERSION="2.2.0"
OFFICIAL_HYDRA_NETWORKS = {"mainnet", "preview", "preprod", "sanchonet"}
LOCAL_HYDRA_SCRIPT_NETWORKS = {"devnet"}
DEVNET_HYDRA_NODE_FUNDING_LOVELACE = 200_000_000
DEVNET_HYDRA_FUNDS_FUNDING_LOVELACE = 500_000_000


def resolve_hydra_version(args):
    return getattr(args, "version", None) or HYDRA_VERSION


def normalize_hydra_network_name(network: str) -> str:
    if network == "sancho":
        return "sanchonet"
    return network


def build_cardano_network_args(network: str) -> List[str]:
    parsed_network = parse_network(network)
    if parsed_network.startswith("--testnet-magic="):
        return ["--testnet-magic", parsed_network.split("=", 1)[1]]
    if parsed_network == "--mainnet":
        return ["--mainnet"]
    return [parsed_network]


def build_hydra_scripts_args(network: str, hydra_version: str) -> List[str]:
    normalized_network = normalize_hydra_network_name(network)
    if normalized_network in OFFICIAL_HYDRA_NETWORKS:
        return ["--network", normalized_network]

    local_scripts_tx_id = get_local_hydra_scripts_tx_id(network, hydra_version)
    if local_scripts_tx_id:
        return ["--hydra-scripts-tx-id", local_scripts_tx_id]

    networks_data = fetch_network_json()
    tx_id = networks_data.get(normalized_network, {}).get(hydra_version)
    if not isinstance(tx_id, str) or not tx_id.strip():
        print(
            f"Error: Could not find Hydra script references for "
            f"{normalized_network}.{hydra_version} in networks.json."
        )
        sys.exit(1)

    if "," in tx_id:
        print(
            f"Error: Hydra {hydra_version} publishes multiple script references for "
            f"{normalized_network}, which adaup can only handle through "
            f"'--network {normalized_network}'."
        )
        sys.exit(1)

    return ["--hydra-scripts-tx-id", tx_id]


def run_script_needs_regeneration(run_script_path: str, network: str) -> bool:
    if not os.path.exists(run_script_path):
        return True

    with open(run_script_path, "r", encoding="utf-8") as f:
        run_script = f.read()

    normalized_network = normalize_hydra_network_name(network)
    if normalized_network in OFFICIAL_HYDRA_NETWORKS and "--hydra-scripts-tx-id" in run_script:
        return True
    if network == "mainnet" and "--testnet-magic 0" in run_script:
        return True
    return False

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
    
    if all(os.path.isfile(file) for file in files):
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


def get_network_dir(cardano_home: str, network: str) -> str:
    return os.path.join(cardano_home, network)


def get_local_hydra_scripts_tx_id_path(cardano_home: str, network: str, hydra_version: str) -> str:
    return os.path.join(get_network_dir(cardano_home, network), f"hydra-scripts-{hydra_version}.txid")


def get_local_hydra_scripts_tx_id(network: str, hydra_version: str, cardano_home: str | None = None) -> str | None:
    if cardano_home is None:
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
    tx_id_path = get_local_hydra_scripts_tx_id_path(cardano_home, network, hydra_version)
    if not os.path.exists(tx_id_path):
        return None
    with open(tx_id_path, "r", encoding="utf-8") as file:
        tx_id = file.read().strip()
    return tx_id or None


def save_local_hydra_scripts_tx_id(cardano_home: str, network: str, hydra_version: str, tx_id: str) -> str:
    network_dir = get_network_dir(cardano_home, network)
    os.makedirs(network_dir, exist_ok=True)
    tx_id_path = get_local_hydra_scripts_tx_id_path(cardano_home, network, hydra_version)
    with open(tx_id_path, "w", encoding="utf-8") as file:
        file.write(tx_id.strip() + "\n")
    return tx_id_path


def ensure_wallet_has_minimum_balance(cli: CardanoCLI, source_wallet, target_wallet, minimum_lovelace: int, tx_name: str):
    target_utxos = query_wallet_utxos_json(cli, target_wallet)
    current_balance = sum(item.get("value", {}).get("lovelace", 0) for item in target_utxos.values())
    if current_balance >= minimum_lovelace:
        return

    top_up_lovelace = minimum_lovelace - current_balance
    print(f"Funding {target_wallet.address} with {top_up_lovelace} lovelace...")
    tx_id = cli.build_and_submit(
        source_wallet,
        tx_name,
        ["--tx-out", f"{target_wallet.address}+{top_up_lovelace}"],
    )
    print(f"Submitted Hydra funding transaction: {tx_id}")
    deadline = time.time() + 30
    while time.time() < deadline:
        target_utxos = query_wallet_utxos_json(cli, target_wallet)
        balance = sum(item.get("value", {}).get("lovelace", 0) for item in target_utxos.values())
        if balance >= minimum_lovelace:
            return
        time.sleep(1)
    raise RuntimeError(f"Timed out funding Hydra wallet {target_wallet.address}")


def query_wallet_utxos_json(cli: CardanoCLI, wallet):
    out_file = os.path.join(os.environ.get("CARDANO_KEYS_DIR", os.path.join(HOME, ".cardano", "keys")), "tmp", "hydra-utxo.json")
    cli.cardano_cli(
        "query",
        "utxo",
        ["--address", wallet.address, "--out-file", out_file],
        include_network=True,
        include_socket=True,
    )
    with open(out_file, "r", encoding="utf-8") as file:
        return json.load(file)


def ensure_devnet_hydra_wallet_funding(cli: CardanoCLI, cardano_home: str, network: str, node_index: int):
    if network != "devnet":
        return

    source_keys_dir = os.environ.get("CARDANO_KEYS_DIR", os.path.join(cardano_home, "keys"))
    source_store = WalletStore(source_keys_dir)
    source_wallet = source_store.load_wallet()

    credentials_dir = os.path.join(cardano_home, network, f"hydra-{node_index}", "credentials")
    target_store = WalletStore(credentials_dir)
    node_wallet = target_store.load_enterprise_wallet(cli, "node")
    funds_wallet = target_store.load_enterprise_wallet(cli, "funds")

    ensure_wallet_has_minimum_balance(
        cli,
        source_wallet,
        node_wallet,
        DEVNET_HYDRA_NODE_FUNDING_LOVELACE,
        f"hydra-node-fund-{node_index}",
    )
    ensure_wallet_has_minimum_balance(
        cli,
        source_wallet,
        funds_wallet,
        DEVNET_HYDRA_FUNDS_FUNDING_LOVELACE,
        f"hydra-funds-fund-{node_index}",
    )


def ensure_local_hydra_scripts(cli: CardanoCLI, cardano_home: str, network: str, hydra_version: str, hydra_node_path: str):
    if network not in LOCAL_HYDRA_SCRIPT_NETWORKS:
        return None

    existing_tx_id = get_local_hydra_scripts_tx_id(network, hydra_version, cardano_home)
    if existing_tx_id:
        return existing_tx_id

    credentials_dir = os.path.join(cardano_home, network, "hydra-0", "credentials")
    signing_key = os.path.join(credentials_dir, "node.sk")
    if not os.path.exists(signing_key):
        raise RuntimeError(
            f"Cannot publish Hydra scripts for {network}: missing signing key {signing_key}"
        )

    print(f"Publishing Hydra scripts for local network {network}...")
    publish_result = subprocess.run(
        [
            hydra_node_path,
            "publish-scripts",
            "--cardano-signing-key",
            signing_key,
            "--node-socket",
            os.path.join(cardano_home, network, "node.socket"),
            "--testnet-magic",
            parse_network(network).split("=", 1)[1],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    if publish_result.stdout:
        print(publish_result.stdout, end="")
    if publish_result.stderr:
        print(publish_result.stderr, end="")
    tx_id = (publish_result.stdout or "").strip().splitlines()[-1].strip()
    if not tx_id:
        raise RuntimeError(f"Could not parse Hydra script publication tx id for {network}")
    save_local_hydra_scripts_tx_id(cardano_home, network, hydra_version, tx_id)
    print(f"Published Hydra scripts for {network}: {tx_id}")
    return tx_id

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
        hydra_version: str,
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
        hydra_version (str): Hydra version used for this node.
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
        "--ledger-protocol-parameters", protocol_params_path,
        "--node-socket", os.path.join(cardano_home, network, "node.socket"),
        "--api-port", str(4001 + node_index),
        "--listen", f"127.0.0.1:{5001 + node_index}",
        "--api-host", "0.0.0.0",
    ]
    run_command.extend(build_hydra_scripts_args(network, hydra_version))
    run_command.extend(build_cardano_network_args(network))

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
    
    run_script_content = f"#!/usr/bin/env bash\n\n{run_command[0]}"
    if len(formatted_command_parts) > 0:
        run_script_content += " \\\n" + " \\\n".join(formatted_command_parts)
    run_script_content += "\n"
    
    run_script_path = os.path.join(hydra_dir, "run.sh")

    with open(run_script_path, "w", encoding="utf-8") as f:
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

    download_and_setup_hydra(HYDRA_VERSION, node_bin_dir)
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
    hydra_version = resolve_hydra_version(args)

    download_and_setup_hydra(hydra_version, node_bin_dir)
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
        ensure_devnet_hydra_wallet_funding(cli, cardano_home, args.network, i)
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
    ensure_local_hydra_scripts(cli, cardano_home, args.network, hydra_version, hydra_node_path)

    for config in node_configs:
        generate_and_save_hydra_run_script(
            node_index=config['index'],
            network=args.network,
            cardano_home=cardano_home,
            node_bin_dir=node_bin_dir,
            hydra_version=hydra_version,
            hydra_node_path=hydra_node_path,
            node_configs=node_configs
        )

    print(f"All run scripts generated with correct peer configurations for {args.no_of_nodes} hydra nodes on network {args.network}.")

def run_hydra_node(args):
    cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
    node_bin_dir = os.path.join(cardano_home, "bin")
    network = args.network if args.network else "preview"
    node_index = args.index
    hydra_version = resolve_hydra_version(args)
    download_and_setup_hydra(hydra_version, node_bin_dir)

    hydra_dir = os.path.join(cardano_home, network, f"hydra-{node_index}")
    run_script_path = os.path.join(hydra_dir, "run.sh")

    if (
        os.path.exists(run_script_path)
        and os.access(run_script_path, os.X_OK)
        and not run_script_needs_regeneration(run_script_path, network)
    ):
        print(f"Executing existing run.sh for hydra node {node_index} on network {network}...")
        exec([run_script_path])
    else:
        print(f"run.sh is missing, outdated, or not executable for node {node_index}. Generating and executing...")

        cli = CardanoCLI(network=network,
                         executable=os.path.join(node_bin_dir, "cardano-cli"),
                         socket_path=os.path.join(cardano_home, network, "node.socket"))

        credentials_dir = os.path.join(hydra_dir, "credentials")
        data_dir = os.path.join(hydra_dir, "data")

        os.makedirs(credentials_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        create_hydra_credentials(cli, credentials_dir)
        ensure_devnet_hydra_wallet_funding(cli, cardano_home, network, node_index)
        generate_protocol_parameters(cli, os.path.join(credentials_dir, "protocol-params.json"))

        hydra_node_path = os.path.join(node_bin_dir, "hydra-node")
        ensure_local_hydra_scripts(cli, cardano_home, network, hydra_version, hydra_node_path)

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
            hydra_version=hydra_version,
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

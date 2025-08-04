import os
import sys
import zipfile
import json
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import shutil
import tqdm
import tempfile
import time
from adaup.commands.cardano_cli import CardanoCLI,Wallet,WalletStore

# Import executor helper from exec module
from .exec import executor,exec

def create_hydra_credentials(cli:CardanoCLI,credentials_dir):
    """
    Create the necessary credentials for a Hydra node.

    Args:
        credentials_dir (str): The directory where the credentials will be stored.
    """
    print(f"Creating hydra credentials in {credentials_dir}...")

    # Get cardano-cli path
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
   

    # Generate hydra key pair using hydra-tools via executor
    hydr_output_file=os.path.join(credentials_dir, "hydra")
    files=[hydr_output_file+".sk",hydr_output_file+".vk"]
    
    # skip if credentials are already present
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


    # Create a temporary file for the raw protocol parameters

    result = cli.cardano_cli("query","protocol-parameters",[],include_network=True,include_socket=True)
    # Query protocol parameters using executor
    params = json.loads(result)

    # Modify parameters to set fees and pricing to 0
    params['txFeeFixed'] = 0
    params['txFeePerByte'] = 0
    params['executionUnitPrices']['priceMemory'] = 0
    params['executionUnitPrices']['priceSteps'] = 0

    # Write modified parameters to output file

    with open(filePath, 'w') as f:
        json.dump(params, f, indent=2)
    return filePath


def fetch_network_json():
    """
    Download and parse the networks.json file from GitHub.

    Returns:
        dict: Parsed JSON content
    """
    url = "https://raw.githubusercontent.com/cardano-scaling/hydra/master/hydra-node/networks.json"
    print(f"Fetching network information from {url}...")

    try:
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(request) as response:
            content = response.read()
            networks = json.loads(content)
            # Return only the mainnet networks for simplicity
            return networks
    except HTTPError as e:
        print(f"HTTP Error {e.code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching network information from {url}: {str(e)}")
        sys.exit(1)

def download_url(url, dest_path):
    print(f"Downloading from {url}...")
    try:
        with urlopen(url) as response, open(dest_path, 'wb') as out_file:
            total_size = int(response.headers.get('Content-Length', 0))
            chunk_size = 8192
            downloaded = 0

            with tqdm.tqdm(total=total_size, unit='B', unit_scale=True, desc="Downloading") as pbar:
                while True:
                    buffer = response.read(chunk_size)
                    if not buffer:
                        break
                    out_file.write(buffer)
                    downloaded += len(buffer)
                    pbar.update(len(buffer))
        return dest_path
    except HTTPError as e:
        print(f"HTTP Error {e.code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"Error downloading from {url}: {str(e)}")
        print(f"Please try to download manually: {url}")
        sys.exit(1)

def check_hydra_present(bin_dir):
    """
    Check if hydra-node and hydra-tui are present in the bin directory.

    Args:
        bin_dir (str): The directory where the executables should reside.

    Returns:
        bool: True if both executables are found, False otherwise.
    """
    hydra_node_path = os.path.join(bin_dir, "hydra-node")
    hydra_tui_path = os.path.join(bin_dir, "hydra-tui")

    return (os.path.isfile(hydra_node_path) and os.access(hydra_node_path, os.X_OK) and
            os.path.isfile(hydra_tui_path) and os.access(hydra_tui_path, os.X_OK))

def download_and_setup_hydra(hydra_version, bin_dir):
    """
    Download and set up the Hydra client binaries.

    Args:
        hydra_version (str): The version of Hydra to download.
        bin_dir (str): The directory where the executable will reside.

    Returns:
        str: Path to the Hydra executable.
    """
    print(f"Downloading and setting up Hydra {hydra_version}...")

    # Check if hydra-node and hydra-tui are already present
    if check_hydra_present(bin_dir):
        print(f"Hydra executables (hydra-node, hydra-tui) already exist at {bin_dir}. Skipping download.")
        return os.path.join(bin_dir)

    # Make sure the bin directory exists for extraction
    os.makedirs(bin_dir, exist_ok=True)

    hydra_archive = f"hydra-x86_64-linux-{hydra_version}.zip"
    url = f"https://github.com/cardano-scaling/hydra/releases/download/{hydra_version}/{hydra_archive}"

    try:
        # Download the archive
        tmp_download_dir = os.path.join(os.path.dirname(bin_dir), "tmp_downloads") # Use parent of bin_dir for tmp
        os.makedirs(tmp_download_dir, exist_ok=True)
        tmp_archive = os.path.join(tmp_download_dir, hydra_archive)
        download_url(url, tmp_archive)

        # Extract the contents of the archive
        with zipfile.ZipFile(tmp_archive, 'r') as zip_ref:
            zip_ref.extractall(bin_dir)

        # Remove the temporary archive file
        os.remove(tmp_archive)

        # Make all moved files executable (if needed)
        hydra_node_path = os.path.join(bin_dir, "hydra-node")
        hydra_tui_path = os.path.join(bin_dir, "hydra-tui")

        if not (os.path.exists(hydra_node_path) and os.path.exists(hydra_tui_path)):
            print(f"Error: Expected executables not found in extracted archive at {bin_dir}")
            return

        # Make the executables executable
        os.chmod(hydra_node_path, 0o755)
        os.chmod(hydra_tui_path, 0o755)

        print(f"Hydra setup complete. Executable at: {bin_dir}")

    except Exception as e:
        print(f"Error setting up Hydra: {str(e)}")
        sys.exit(1)
    finally:
        # Cleanup temp directory
        if os.path.exists(tmp_download_dir):
            shutil.rmtree(tmp_download_dir)

    return bin_dir

def run_hydra_node(
        bin_dir,
        network="mainnet",
        node_index=0,
        cardano_signing_key=None,
        hydra_signing_key=None,
        protocol_params_path=None):
    """
    Run the hydra-node command with all required parameters.

    Args:
        bin_dir (str): The directory where the hydra-node executable is located.
        network (str): The Cardano network to run on (e.g., mainnet, testnet).
        node_index (int): The index of this hydra node.
        cardano_signing_key (str): Path to the Cardano signing key file.
        hydra_signing_key (str): Path to the Hydra signing key file.
        protocol_params_path (str): Path to the ledger protocol parameters JSON file.
    """
    print(f"Running hydra-node for node {node_index} on {network} network...")

    try:
        # Get absolute paths if relative paths are provided
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))

        hydra_node_path = os.path.join(bin_dir, "hydra-node")
        if not os.path.isfile(hydra_node_path) or not os.access(hydra_node_path, os.X_OK):
            print(f"Error: Executable 'hydra-node' not found in {bin_dir}")
            sys.exit(1)

        # Ensure required parameters are provided
        if cardano_signing_key is None:
            print("Error: cardano-signing-key is required")
            sys.exit(1)
        if hydra_signing_key is None:
            print("Error: hydra-signing-key is required")
            sys.exit(1)
        if protocol_params_path is None:
            print("Error: ledger-protocol-parameters is required")
            sys.exit(1)

        # Get network information
        node_version="0.22.0"
        networks = fetch_network_json()
        
        # this list is comma separated string
        tx_id_list = networks.get(network,{}).get(node_version, [])

        if not isinstance(tx_id_list, str):
            print(json.dumps(networks,indent=2))
            print(f"Error: Could not find transaction ID for {network}.{node_version} in the network configuration.")
            sys.exit(1)

        # For now, just use the first tx_id (in a real implementation we might need to handle multiple)
        tx_id = tx_id_list

        # Determine testnet magic based on network
        testnet_magic = 2 if network != "mainnet" else 0

        # Build the command with all parameters
        cmd = [
            hydra_node_path,
            "--node-id", f"node-{network}-{node_index}",
            "--persistence-dir", os.path.join(cardano_home, network, "hydra-"+str(node_index), "data"),
            "--cardano-signing-key", cardano_signing_key,
            "--hydra-signing-key", hydra_signing_key,
            "--hydra-scripts-tx-id", tx_id,
            "--ledger-protocol-parameters", protocol_params_path,
            "--testnet-magic", str(testnet_magic),
            "--node-socket", os.path.join(cardano_home, network, "node.socket"),
            "--api-port", str(4001 + node_index),  # Use unique port for each node
            "--listen", f"127.0.0.1:{5001 + node_index}",  # Use unique listen address for each node
            "--api-host", "127.0.0.1",
        ]

        # Add peer information if available (for multi-node setups)
        peers = []
        missing=[]
        for i in range(2):  # Example: add up to 2 potential peers
            if i != node_index and os.path.exists(os.path.join(cardano_home, network, "hydra", str(i), "credentials")):
                peer_vk_path = os.path.join(cardano_home, network, "hydra", str(i), "credentials", "node.vk")
                hydra_vk_path = os.path.join(cardano_home, network, "hydra", str(i), "credentials", "hydra.vk")
                node_vk_exists=os.path.exists(peer_vk_path)
                missing=[]
                peer=[]
                if os.path.exists(peer_vk_path) :
                    peer.append("--peer=127.0.0.1:"+str(5001+node_index))
                    peer.append(f"--cardano-verification-key={peer_vk_path}")
                else:
                    missing.append(peer_vk_path)
                    
                if  os.path.exists(hydra_vk_path):
                    peer.append(f"--hydra-verification-key={hydra_vk_path}")
                else:
                    missing.append(hydra_vk_path)
                        
                if len(missing)> 0:
                    print(f"Missing keys for peer {i}")
                    [print(" -",x) for x in missing]
                else:
                    peers.extend(peer)            

        # Add peer parameters to the command
        cmd.extend(peers)

        print(f"Executing command: {' '.join(cmd)}")

        # Execute the command using executor
        executor(cmd, show_command=True, stream_output=True,throw_error=False)
    except Exception as e:
        print(f"Unexpected error while running hydra-node: {str(e)}")
        sys.exit(1)

def generate_and_save_hydra_run_script(
        node_index: int,
        network: str,
        cardano_home: str,
        node_bin_dir: str,
        tx_id: str,
        testnet_magic: int,
        hydra_node_path: str,
        node_configs: list = None # List of all node configs for peer discovery
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

    # Ensure directories exist (they should be created by bootstrap or node command)
    os.makedirs(credentials_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    cardano_signing_key = os.path.join(credentials_dir, "node.sk")
    hydra_signing_key = os.path.join(credentials_dir, "hydra.sk")
    protocol_params_path = os.path.join(credentials_dir, "protocol-params.json")

    # Ensure required files exist before building command
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

    # Add peer information (full mesh) if node_configs are provided
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

    # Format the command for multi-line readability in run.sh
    formatted_command_parts = []
    cmd_idx = 1 # Start from the first argument, skipping the executable
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
    os.chmod(run_script_path, 0o755) # Make the script executable

    print(f"Created run.sh for node {node_index} at {run_script_path}")
    return True

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

# Import executor helper from exec module
from .exec import executor,exec

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

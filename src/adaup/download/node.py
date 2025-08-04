import os
import sys
import platform
import tarfile
import zipfile
from urllib.request import urlopen
from urllib.error import HTTPError

import shutil
import tqdm

# Import executor helper from exec module
from .exec import executor

def check_cardano_node_present(node_bin_dir):
    """
    Check if cardano-node and cardano-cli are present in the bin directory.

    Args:
        node_bin_dir (str): The directory where the executable should reside.

    Returns:
        bool: True if both executables are found, False otherwise.
    """
    cardano_node_path = os.path.join(node_bin_dir, "cardano-node")
    cardano_cli_path = os.path.join(node_bin_dir, "cardano-cli")

    return os.path.isfile(cardano_node_path) and os.path.isfile(cardano_cli_path)

def safe_move(src, dst):
    """
    Safely move a file or directory from src to dst, handling cross-device links.

    Args:
        src (str): Source path (file or directory).
        dst (str): Destination path (file or directory).

    Raises:
        OSError: If there's an error moving the file/directory that isn't related
                 to cross-device linking.
    """
    try:
        # First attempt to rename using os.rename for same filesystem
        os.rename(src, dst)
    except OSError as e:
        if "Invalid cross-device link" in str(e):
            # If cross-device link error occurs, use shutil.move instead
            shutil.move(src, dst)
        else:
            # Re-raise other errors
            raise

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

def extract_archive(archive_path, extract_to):
    print(f"Extracting {archive_path} to {extract_to} using external command...")
    if archive_path.endswith('.tar.gz'):
        try:
            # Execute tar command with executor
            executor(["tar", "-xzf", archive_path, "-C", extract_to], show_command=True, throw_error=True)
        except Exception as e:
            print(f"Error extracting tar.gz archive: {e}")
            sys.exit(1)
    elif archive_path.endswith('.zip'):
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
    else:
        print("Unknown file extension provided to extract function :"+archive_path)
        sys.exit(1)
    print("Extraction complete.")

def check_cardano_node_present(node_bin_dir):
    """
    Check if cardano-node and cardano-cli are present in the bin directory.

    Args:
        node_bin_dir (str): The directory where the executable should reside.

    Returns:
        bool: True if both executables are found, False otherwise.
    """
    cardano_node_path = os.path.join(node_bin_dir, "cardano-node")
    cardano_cli_path = os.path.join(node_bin_dir, "cardano-cli")

    return os.path.isfile(cardano_node_path) and os.path.isfile(cardano_cli_path)

def download_and_setup_cardano_node(node_version, cardano_home, node_bin_dir):
    """
    Download and set up the Cardano node binaries.

    Args:
        node_version (str): The version of the Cardano node to download.
        cardano_home (str): The home directory where binaries will be installed.
        node_bin_dir (str): The directory where the executable will reside.

    Returns:
        str: Path to the Cardano node executable.
    """
    print(f"Downloading and setting up Cardano node {node_version}...")

    # Check if cardano-node and cardano-cli are already present
    if check_cardano_node_present(node_bin_dir):
        node_bin_path = os.path.join(node_bin_dir, "cardano-node")
        print(f"Cardano node and cardano-cli already exist at {node_bin_dir}. Skipping download.")
        return node_bin_path

    current_platform = platform.system().lower()
    archive_file=""
    if current_platform == "linux":
        archive_file=f"cardano-node-{node_version}-linux.tar.gz"
        url = f"https://github.com/IntersectMBO/cardano-node/releases/download/{node_version}/{archive_file}"
    elif current_platform == "darwin":
        archive_file=f"cardano-node-{node_version}-macos.tar.gz"
        url = f"https://github.com/IntersectMBO/cardano-node/releases/download/{node_version}/{archive_file}"
    elif current_platform in ["windows", "cygwin"]:
        archive_file=f"cardano-node-{node_version}-win64.zip"
        url = f"https://github.com/IntersectMBO/cardano-node/releases/download/{node_version}/{archive_file}"
    else:
        print(f"Unsupported platform: {current_platform}")
        sys.exit(1)

    node_bin_path = os.path.join(node_bin_dir, "cardano-node")
    if os.path.isfile(node_bin_path):
        print(f"Cardano node already exists at {node_bin_path}. Skipping download.")
        return node_bin_path

    tmp_download_dir = os.path.join(cardano_home, "tmp_downloads")
    os.makedirs(tmp_download_dir, exist_ok=True)
    tmp_archive = os.path.join(tmp_download_dir, archive_file)

    try:
        download_url(url, tmp_archive)
        print(f"Extracting {tmp_archive} directly to {cardano_home}...")
        extract_archive(tmp_archive, cardano_home)
        print(f"Contents of {cardano_home} after extraction:")
        # Execute ls command with executor
        executor(["ls", "-R", cardano_home], show_command=True, throw_error=False)

        os.remove(tmp_archive)

        extracted_items = os.listdir(cardano_home)
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(cardano_home, extracted_items[0])):
            single_root_dir = os.path.join(cardano_home, extracted_items[0])
            print(f"Detected single top-level directory after extraction: {single_root_dir}. Moving contents up...")
            for item in os.listdir(single_root_dir):
                src_path = os.path.join(single_root_dir, item)
                dst_path = os.path.join(cardano_home, item)
                safe_move(src_path, dst_path)
            shutil.rmtree(single_root_dir)
            print("Contents moved to root of ~/.cardano and temporary directory removed.")

        if not os.path.exists(node_bin_path):
            print(f"Error: cardano-node executable not found at expected path: {node_bin_path}")
            sys.exit(1)
        else:
            print(f"Cardano node executable is at: {node_bin_path}")
        return node_bin_path

    except HTTPError as e:
        print(f"HTTP Error {e.code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"Error downloading or extracting Cardano node: {str(e)}")
        sys.exit(1)
    finally:
        if os.path.exists(tmp_download_dir):
            shutil.rmtree(tmp_download_dir)

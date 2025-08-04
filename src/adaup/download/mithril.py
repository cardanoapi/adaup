import os
import sys
from urllib.request import urlopen
from urllib.error import HTTPError

# Import executor helper from exec module
from .exec import executor

def download_url(url, dest_path):
    print(f"Downloading from {url}...")
    try:
        with urlopen(url) as response, open(dest_path, 'wb') as out_file:
            total_size = int(response.headers.get('Content-Length', 0))
            chunk_size = 8192
            downloaded = 0

            print(f"Downloading {dest_path}...")

            while True:
                buffer = response.read(chunk_size)
                if not buffer:
                    break
                out_file.write(buffer)
                downloaded += len(buffer)
    except HTTPError as e:
        print(f"HTTP Error {e.code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"Error downloading from {url}: {str(e)}")
        print(f"Please try to download manually: {url}")
        sys.exit(1)

def check_mithril_client_present(executable_path):
    """
    Check if mithril-client is present as an executable.

    Args:
        executable_path (str): The path where the executable should reside.

    Returns:
        bool: True if executable is found, False otherwise.
    """
    return os.path.isfile(executable_path) and os.access(executable_path, os.X_OK)

def download_and_setup_mithril(bin_dir):
    """
    Download and set up the Mithril client binaries.

    Args:
        bin_dir (str): The directory where the executable will reside.

    Returns:
        str: Path to the Mithril client executable.
    """
    print("Downloading and setting up Mithril client...")
    mithril_client_path = os.path.join(bin_dir, "mithril-client")

    # Check if mithril-client is already present
    if check_mithril_client_present(mithril_client_path):
        print(f"Mithril client already exists at {mithril_client_path}. Skipping download.")
        return mithril_client_path

    if os.path.exists(mithril_client_path):
        print(f"Mithril client already exists at {mithril_client_path}. Skipping download.")
        return

    try:
        command = f"curl --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/input-output-hk/mithril/refs/heads/main/mithril-install.sh | sh -s -- -c mithril-client -d latest -p {bin_dir}"
        # Execute the command using executor
        executor(command, shell=True, show_command=True, throw_error=True)
        os.chmod(mithril_client_path, 0o755) # Make executable
        print(f"Mithril client setup complete. Executable at: {mithril_client_path}")
    except Exception as e:
        print(f"Error setting up Mithril client: {str(e)}")
        sys.exit(1)

    return mithril_client_path

def run_mithril_client(bin_dir):
    """
    Run the mithril-client command from the specified bin directory.

    Args:
        bin_dir (str): The directory where the mithril-client executable is located.
    """
    print("Running mithril-client...")
    try:
        mithril_client_path = os.path.join(bin_dir, "mithril-client")
        if not os.path.isfile(mithril_client_path) or not os.access(mithril_client_path, os.X_OK):
            print(f"Error: Executable 'mithril-client' not found in {bin_dir}")
            sys.exit(1)

        # Execute the command using executor
        executor([mithril_client_path], show_command=True, throw_error=True)
    except Exception as e:
        print(f"Unexpected error while running mithril-client: {str(e)}")
        sys.exit(1)

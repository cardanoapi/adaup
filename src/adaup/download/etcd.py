import os
import sys
from urllib.request import urlopen
from urllib.error import HTTPError

# Import executor helper from exec module
from .exec import executor

def download_url(url, dest_path):
    """Download a file from URL to destination path."""
    print(f"Downloading {url}...")
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
        return dest_path
    except HTTPError as e:
        print(f"HTTP Error {e.code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"Error downloading from {url}: {str(e)}")
        print(f"Please try to download manually: {url}")
        sys.exit(1)

def check_etcd_present(bin_dir):
    """
    Check if etcd and etcdctl are present in the bin directory.

    Args:
        bin_dir (str): The directory where the executables should reside.

    Returns:
        bool: True if both executables are found, False otherwise.
    """
    etcd_path = os.path.join(bin_dir, "etcd")
    etcdctl_path = os.path.join(bin_dir, "etcdctl")

    return (os.path.isfile(etcd_path) and os.access(etcd_path, os.X_OK) and
            os.path.isfile(etcdctl_path) and os.access(etcdctl_path, os.X_OK))

def download_and_setup_etcd(version, bin_dir):
    """
    Download and set up Etcd.

    Args:
        version (str): The version of Etcd to download.
        bin_dir (str): The directory where the executables will reside.

    Returns:
        str: Path to the Etcd installation directory.
    """
    print(f"Downloading and setting up Etcd {version}...")

    # Check if etcd is already present
    if check_etcd_present(bin_dir):
        print(f"Etcd executables (etcd, etcdctl) already exist at {bin_dir}. Skipping download.")
        return bin_dir

    platform = "linux-amd64"
    url = f"https://github.com/etcd-io/etcd/releases/download/{version}/etcd-{version}-{platform}.tar.gz"

    try:
        # Create a temporary directory for the download
        tmp_dir = os.path.join(bin_dir, "tmp_etcd")
        os.makedirs(tmp_dir, exist_ok=True)

        # Download the archive to temp dir
        download_url(url, os.path.join(tmp_dir, f"etcd-{version}-{platform}.tar.gz"))

        # Extract the archive
        import tarfile
        with tarfile.open(os.path.join(tmp_dir, f"etcd-{version}-{platform}.tar.gz"), "r:gz") as tar:
            tar.extractall(path=tmp_dir)

        # Move executables to bin directory
        etcd_src = os.path.join(tmp_dir, f"etcd-{version}-{platform}", "etcd")
        etcdctl_src = os.path.join(tmp_dir, f"etcd-{version}-{platform}", "etcdctl")

        if not (os.path.exists(etcd_src) and os.path.exists(etcdctl_src)):
            print(f"Error: Expected executables not found in extracted archive at {tmp_dir}")
            return

        # Make sure the bin directory exists
        os.makedirs(bin_dir, exist_ok=True)

        # Move executables to bin directory
        etcd_dest = os.path.join(bin_dir, "etcd")
        etcdctl_dest = os.path.join(bin_dir, "etcdctl")

        if os.path.exists(etcd_dest):
            os.remove(etcd_dest)
        if os.path.exists(etcdctl_dest):
            os.remove(etcdctl_dest)

        import shutil
        shutil.copy2(etcd_src, etcd_dest)
        shutil.copy2(etcdctl_src, etcdctl_dest)

        # Make the executables executable (if not already)
        os.chmod(etcd_dest, 0o755)  # Make executable
        os.chmod(etcdctl_dest, 0o755)  # Make executable

        # Clean up temporary files
        import shutil
        shutil.rmtree(tmp_dir)

        print(f"Etcd setup complete. Executables at: {bin_dir}")
    except Exception as e:
        print(f"Error setting up Etcd: {str(e)}")
        sys.exit(1)

    return bin_dir

def run_etcd(bin_dir):
    """
    Run the etcd command from the specified bin directory.

    Args:
        bin_dir (str): The directory where the etcd executable is located.
    """
    print("Running etcd...")
    try:
        etcd_path = os.path.join(bin_dir, "etcd")
        if not os.path.isfile(etcd_path) or not os.access(etcd_path, os.X_OK):
            print(f"Error: Executable 'etcd' not found in {bin_dir}")
            sys.exit(1)

        # Execute etcd using the executor function
        executor([etcd_path], show_command=True, throw_error=True)
    except Exception as e:
        print(f"Unexpected error while running etcd: {str(e)}")
        sys.exit(1)

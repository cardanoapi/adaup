import os
import shutil
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_MITHRIL_DISTRIBUTION = "latest"

MITHRIL_NETWORK_CONFIGS = {
    "mainnet": {
        "aggregator_endpoint": "https://aggregator.release-mainnet.api.mithril.network/aggregator",
        "genesis_verification_key_url": "https://raw.githubusercontent.com/input-output-hk/mithril/main/mithril-infra/configuration/release-mainnet/genesis.vkey",
        "ancillary_verification_key_url": "https://raw.githubusercontent.com/input-output-hk/mithril/main/mithril-infra/configuration/release-mainnet/ancillary.vkey",
    },
    "preprod": {
        "aggregator_endpoint": "https://aggregator.release-preprod.api.mithril.network/aggregator",
        "genesis_verification_key_url": "https://raw.githubusercontent.com/input-output-hk/mithril/main/mithril-infra/configuration/release-preprod/genesis.vkey",
        "ancillary_verification_key_url": "https://raw.githubusercontent.com/input-output-hk/mithril/main/mithril-infra/configuration/release-preprod/ancillary.vkey",
    },
    "preview": {
        "aggregator_endpoint": "https://aggregator.pre-release-preview.api.mithril.network/aggregator",
        "genesis_verification_key_url": "https://raw.githubusercontent.com/input-output-hk/mithril/main/mithril-infra/configuration/pre-release-preview/genesis.vkey",
        "ancillary_verification_key_url": "https://raw.githubusercontent.com/input-output-hk/mithril/main/mithril-infra/configuration/pre-release-preview/ancillary.vkey",
    },
}

def normalize_network(network):
    if network == "testnet":
        return "preprod"
    return network

def fetch_text(url):
    request = Request(url, headers={"User-Agent": "adaup"})
    try:
        with urlopen(request) as response:
            return response.read().decode("utf-8").strip()
    except HTTPError as e:
        raise RuntimeError(f"HTTP Error {e.code} for URL: {url}") from e
    except Exception as e:
        raise RuntimeError(f"Error downloading {url}: {str(e)}") from e

def get_mithril_network_configuration(network):
    return MITHRIL_NETWORK_CONFIGS.get(normalize_network(network))

def check_mithril_client_present(executable_path):
    return os.path.isfile(executable_path) and os.access(executable_path, os.X_OK)

def download_and_setup_mithril(bin_dir, distribution=DEFAULT_MITHRIL_DISTRIBUTION):
    """
    Download and set up the Mithril client binary with the official installer.
    """
    print("Downloading and setting up Mithril client...")
    os.makedirs(bin_dir, exist_ok=True)
    mithril_client_path = os.path.join(bin_dir, "mithril-client")

    if check_mithril_client_present(mithril_client_path):
        print(f"Mithril client already exists at {mithril_client_path}. Skipping download.")
        return mithril_client_path

    installer_cmd = (
        "curl --proto '=https' --tlsv1.2 -sSf "
        "https://raw.githubusercontent.com/input-output-hk/mithril/main/mithril-install.sh "
        f"| sh -s -- -c mithril-client -d {distribution} -p {bin_dir}"
    )
    try:
        subprocess.run(["bash", "-lc", installer_cmd], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error setting up Mithril client: {str(e)}")
        sys.exit(1)

    if not check_mithril_client_present(mithril_client_path):
        print(f"Error: mithril-client executable not found at {mithril_client_path}")
        sys.exit(1)

    print(f"Mithril client setup complete. Executable at: {mithril_client_path}")
    return mithril_client_path

def has_db_content(path):
    if not os.path.exists(path):
        return False
    for _, _, files in os.walk(path):
        if files:
            return True
    return False

def is_cardano_db_empty(db_dir):
    """
    Treat a DB as empty until it has immutable, ledger, or volatile content.
    """
    return not any(
        has_db_content(os.path.join(db_dir, subdir))
        for subdir in ("immutable", "ledger", "volatile")
    )

def bootstrap_cardano_db_with_mithril(
    network,
    db_dir,
    bin_dir,
    distribution=DEFAULT_MITHRIL_DISTRIBUTION,
):
    """
    Bootstrap an empty cardano-node DB with a Mithril cardano-db snapshot.
    """
    normalized_network = normalize_network(network)
    config = get_mithril_network_configuration(normalized_network)
    if config is None:
        print(f"Mithril bootstrap is not configured for network {network}. Skipping.")
        return False

    mithril_client_path = download_and_setup_mithril(bin_dir, distribution)
    os.makedirs(db_dir, exist_ok=True)
    staging_dir = os.path.join(os.path.dirname(db_dir), ".mithril-bootstrap")
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    print(f"Bootstrapping {normalized_network} database with Mithril...")
    genesis_verification_key = fetch_text(config["genesis_verification_key_url"])
    ancillary_verification_key = fetch_text(config["ancillary_verification_key_url"])

    cmd = [
        mithril_client_path,
        "--aggregator-endpoint",
        config["aggregator_endpoint"],
        "cardano-db",
        "download",
        "latest",
        "--genesis-verification-key",
        genesis_verification_key,
        "--include-ancillary",
        "--ancillary-verification-key",
        ancillary_verification_key,
        "--allow-override",
        "--download-dir",
        staging_dir,
    ]
    print(f"Executing: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)

        nested_db_dir = os.path.join(staging_dir, "db")
        source_db_dir = nested_db_dir if os.path.isdir(nested_db_dir) else staging_dir

        for entry in os.listdir(db_dir):
            entry_path = os.path.join(db_dir, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)

        for entry in os.listdir(source_db_dir):
            shutil.move(os.path.join(source_db_dir, entry), os.path.join(db_dir, entry))
    finally:
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir)

    if is_cardano_db_empty(db_dir):
        raise RuntimeError(f"Mithril bootstrap did not populate {db_dir}")

    print(f"Mithril bootstrap completed for {normalized_network} at {db_dir}.")
    return True

def run_mithril_client(bin_dir, distribution=DEFAULT_MITHRIL_DISTRIBUTION):
    print("Running mithril-client...")
    mithril_client_path = download_and_setup_mithril(bin_dir, distribution)
    subprocess.run([mithril_client_path], check=True)

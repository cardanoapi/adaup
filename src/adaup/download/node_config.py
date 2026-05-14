"""
Cardano node configuration utilities.
"""

import json
import os

def get_config_urls(network):
    """
    Generate configuration URLs based on the network type.

    Args:
        network: The network to generate configs for ('preview' or 'mainnet')

    Returns:
        A list of tuples with (url, filename)

    Raises:
        ValueError: If an unsupported network is specified
    """
    files=[]
    # Normalize network name for testnet/preview compatibility
    if network == "testnet":
        network = "preprod"

    if network in ("preview", "preprod", "mainnet"):
        files = [
            ("https://book.play.dev.cardano.org/environments/{network}/config.json","config.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/db-sync-config.json", "db-sync-config.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/submit-api-config.json", "submit-api-config.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/topology.json", "topology.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/peer-snapshot.json", "peer-snapshot.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/byron-genesis.json", "byron-genesis.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/shelley-genesis.json", "shelley-genesis.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/alonzo-genesis.json", "alonzo-genesis.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/conway-genesis.json", "conway-genesis.json"),
            ("https://book.play.dev.cardano.org/environments/{network}/guardrails-script.plutus", "guardrails-script.plutus")
        ]
    else:
        raise ValueError(f"Unsupported network: {network}")
    return files

def get_optional_config_urls(network, config_dir):
    """
    Discover optional config artifacts referenced by config.json.

    Args:
        network: Normalized network name.
        config_dir: Directory where the configuration files are stored.

    Returns:
        A list of tuples with (url, filename)
    """
    config_path = os.path.join(config_dir, "config.json")
    if not os.path.exists(config_path):
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error reading config.json for optional artifacts: {exc}")
        return []

    optional_files = []
    checkpoints_file = config.get("CheckpointsFile")
    if checkpoints_file:
        optional_files.append(
            (
                f"https://book.play.dev.cardano.org/environments/{network}/{checkpoints_file}",
                checkpoints_file,
            )
        )
    return optional_files

def ensure_config_file(url, filename, network, config_dir):
    """
    Ensure a single network configuration file exists locally.
    """
    local_path = os.path.join(config_dir, filename)
    if os.path.exists(local_path):
        return True

    print(f"{filename} is missing. Checking for default location...")

    alternative_paths = [
        f"/etc/cardano/{network}/{filename}",
        f"/usr/share/doc/cardano-node-{network}/{filename}",
        os.path.join(os.path.expanduser("~/.cardano"), network, "configuration", filename),
    ]

    for alt_path in alternative_paths:
        if os.path.exists(alt_path):
            print(f"Found {filename} at {alt_path}, copying to {config_dir}...")
            try:
                import shutil
                shutil.copy2(alt_path, local_path)
                return True
            except Exception as e:
                print(f"Error copying config: {str(e)}")

    print(f"{filename} is missing. Downloading...")
    try:
        from urllib.request import urlopen
        with urlopen(url) as response, open(local_path, 'wb') as out_file:
            chunk_size = 8192

            print(f"Downloading {filename}...")

            while True:
                buffer = response.read(chunk_size)
                if not buffer:
                    break
                out_file.write(buffer)
        return True
    except Exception as e:
        print(f"Error downloading {filename}: {str(e)}")
        return False

def download_network_configs(network, config_dir):
    """
    Download configuration files based on the network type.

    Args:
        network: The network to download configs for ('preview' or 'mainnet')
        config_dir: Directory where the configurations will be stored

    Raises:
        ValueError: If an unsupported network is specified
    """
    # Get URLs with network parameter
    normalized_network = "preprod" if network == "testnet" else network
    config_urls = [(url.format(network=normalized_network), filename) for url, filename in get_config_urls(normalized_network)]

    missing_files = []
    for url, filename in config_urls:
        if not ensure_config_file(url, filename, normalized_network, config_dir):
            missing_files.append(filename)

    optional_urls = get_optional_config_urls(normalized_network, config_dir)
    for url, filename in optional_urls:
        if not ensure_config_file(url, filename, normalized_network, config_dir):
            missing_files.append(filename)

    expected_files = [filename for _, filename in config_urls]
    expected_files.extend(filename for _, filename in optional_urls)
    missing_files.extend(
        filename for filename in expected_files
        if not os.path.exists(os.path.join(config_dir, filename))
    )

    if missing_files:
        missing_names = ", ".join(sorted(set(missing_files)))
        raise RuntimeError(
            f"Missing required Cardano config files for {network}: {missing_names}"
        )

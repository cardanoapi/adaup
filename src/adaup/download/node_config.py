"""
Cardano node configuration utilities.
"""

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
    if network == 'mainnet':
        files.append(("https://book.play.dev.cardano.org/environments/mainnet/checkpoints.json","checkpoints.json"))
    return files

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
    config_urls = get_config_urls(network)
    config_urls = [(url.format(network=network), filename) for url, filename in config_urls]

    # Check for existing configs and download if missing
    for url, filename in config_urls:
        local_path = os.path.join(config_dir, filename)

        # First check if there's a local config file already available
        # This is useful for testnet where we might need to manually provide the configuration
        if not os.path.exists(local_path):
            print(f"{filename} is missing. Checking for default location...")

            # Check in parent directory structure for common config locations
            alternative_paths = [
                f"/etc/cardano/{network}/{filename}",
                f"/usr/share/doc/cardano-node-{network}/{filename}",
                f"/home/sudip/.cardano/preview/configuration/{filename}"
            ]

            found_alternative = False
            for alt_path in alternative_paths:
                if os.path.exists(alt_path):
                    print(f"Found {filename} at {alt_path}, copying to {config_dir}...")
                    try:
                        import shutil
                        shutil.copy2(alt_path, local_path)
                        found_alternative = True
                        break
                    except Exception as e:
                        print(f"Error copying config: {str(e)}")

            # If no alternative was found or copy failed, attempt download
            if not os.path.exists(local_path) and not found_alternative:
                print(f"{filename} is missing. Downloading...")
                try:
                    from urllib.request import urlopen
                    with urlopen(url) as response, open(local_path, 'wb') as out_file:
                        total_size = int(response.headers.get('Content-Length', 0))
                        chunk_size = 8192
                        downloaded = 0

                        print(f"Downloading {filename}...")

                        while True:
                            buffer = response.read(chunk_size)
                            if not buffer:
                                break
                            out_file.write(buffer)
                            downloaded += len(buffer)
                except Exception as e:
                    print(f"Error downloading {filename}: {str(e)}")
                    # Don't exit on failure - continue with what we have or user-provided configs

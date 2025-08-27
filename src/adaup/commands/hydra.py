import os
import shutil
import glob
import json
import argparse

from adaup.commands.cardano_cli import CardanoCLI
from adaup.download.hydra import generate_protocol_parameters

HOME = os.environ.get("HOME", "/root")

def reset_hydra_data(cli: CardanoCLI, network_name: str):
    """
    Deletes all contents of hydra-{n}/data/** and re-queries protocol parameters.
    """
    print(f"Resetting Hydra data for network: {network_name}")

    cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
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
            # Initialize CardanoCLI with the correct network and socket path
            cli_instance = CardanoCLI(network=network_name,
                                      executable=os.path.join(cardano_home, "bin", "cardano-cli"),
                                      socket_path=os.path.join(cardano_home, network_name, "node.socket"))
            generate_protocol_parameters(cli_instance, protocol_params_file)
            print(f"Protocol parameters updated in {protocol_params_file}.")
        else:
            print(f"Credentials directory {credentials_dir} does not exist. Skipping protocol parameter update.")

    print(f"Hydra reset complete for network {network_name}.")


def run(args):
    """
    Entry point for hydra commands.
    """
    if args.subcommand == "reset":
        cardano_home = os.environ.get("CARDANO_HOME", os.path.expanduser("~/.cardano"))
        node_bin_dir = os.path.join(cardano_home, "bin")
        cli = CardanoCLI(network=args.network,
                         executable=os.path.join(node_bin_dir, "cardano-cli"),
                         socket_path=os.path.join(cardano_home, args.network, "node.socket"))
        reset_hydra_data(cli, args.network)
    else:
        print(f"Unknown hydra subcommand: {args.subcommand}")
        # This part should ideally be handled by argparse, but as a fallback
        # you might want to print help or raise an error.

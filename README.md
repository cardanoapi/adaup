

## Installation

**⚠️ Warning:** Only **x86/64 Linux** platform is supported.



```bash
pip install adaup
```

#### SystemWide Installation
```
sudo pip install --upgrade adaup --break-system-packages
```
After installation, the `cardano` executable will be available in your PATH.

## Usage

The `cardano` executable provides a command-line interface to manage Cardano and Hydra nodes.

### Running a Cardano Node

To start a Cardano node for a specific network (e.g., `preview` or `preprod` or `mainnet` ), use the `node` command:

```bash
cardano node preview
```

You can also specify a different network or node version:

```bash
cardano node mainnet 
```

### Running Cardano CLI Commands

To execute `cardano-cli` commands, use the `cli` subcommand followed by the `cardano-cli` arguments:

```bash
export CARDANO_NODE_SOCKET_PATH=~/.cardano/preview/node.socket
cardano cli query tip --testnet-magic 2
cardano cli query tip --testnet-magic=2 --socket-path=~/.cardano/preview/node.socket ## socket path in the cli
```

### Running a Hydra Cluster

To set up and run a Hydra cluster:

1.  **Bootstrap Hydra Node Credentials:**
    Generate the necessary folders and credentials for your Hydra nodes. This will create `hydra-{n}` directories under `$HOME/.cardano/<network_name>/`.

    **e.g.** this will generate configuration for running 2 hydra nodes.
    ```bash
    cardano hydra bootstrap preview  2
    ```

2.  **Start 1st Hydra Node:**
    

    ```bash
    cardano hydra node preview  0
    ```
2.  **Start 2nd Hydra Node in different terminal:**
    

    ```bash
    cardano hydra node preview  1
    ```
    **Note** the command to run this node is available at `~/.cardano/preview/hydra-0/run.sh`

3.  **Watch hydra status in  Hydra TUI :**
    To interact with a running Hydra node, you can open the Text User Interface (TUI):

    ```bash
    cardano hydra tui  0
    ```

4.  **Reset Hydra Head Data :**
    Shutdown you nodes, and use `reset` command to restart a new hydra head with same configurations. You can then start the nodes again.

    ```bash
    cardano hydra reset preview
    ```

5.  **Prune Hydra Cluster :**
    To remove all keys, data and cluster information. You need to `bootstrap` the cluster again.

    ```bash
    cardano hydra prune preview
    ```

## Generated Directory Structure

For each network, adaup will generate following directory structure in the `$HOME/.cardano` directory.

```
$HOME/
└── .cardano
    ├── bin
    │   └── ... # common binary files cardano-node, cardano-cli, hydra-node etc.
    ├── mainnet
    │   │── configuration
    │   │── db
    │   │── hydra-{index}  
    │   └── ...  
    ├── preview (same as mainnet)
    │   └── ...
    ├── preprod (same as mainnet)
    │   └── ...
```

## Installation

Officially supported platforms:

- Linux `x86_64`
- Linux `arm64`
- macOS Apple Silicon `arm64`

Intel macOS is currently out of scope.

```bash
pip install adaup
```

### System-Wide Installation

```bash
sudo pip install --upgrade adaup --break-system-packages
```

After installation, the `cardano` executable will be available in your `PATH`.

## Usage

The `cardano` executable provides a command-line interface to manage Cardano nodes and related tooling.

### Running a Cardano Node

Start a Cardano node for a specific network:

```bash
cardano node preview
cardano node mainnet
```

For a local single-node development network with prepackaged genesis material and an auto-funded default wallet in `~/.cardano/keys`, use:

```bash
cardano node devnet
```

This starts a local node at `~/.cardano/devnet/node.socket` using `cardano-node 11.0.1`, regenerates `payment.*`, `stake.*`, and `payment.addr` under `~/.cardano/keys` on each run, and funds that address with `1000000000000` lovelace (1,000,000 ADA) from the devnet faucet.

### Docker Devnet

For an isolated Conway devnet with working governance, kuber and cardano-db-sync, needing only docker:

```bash
cardano devnet up --docker -d --wait   # fresh genesis every run
cardano devnet smoke --docker          # register DReps, submit and vote on every governance action
cardano devnet down --docker
```

`--koios` adds the Koios API (port 8053) and `--blockfrost` the Blockfrost API (blockfrost-ryo, port 8054, whole-second slots) over the same chain.

Keys (faucet, pool, committee), configuration and the rendered `docker-compose.yml` are written to `~/.cardano/devnet-docker`. Options, `ADAUP_DEVNET_*` variables and how to attach other compose projects: [Docker Devnet Guide](docs/devnet-docker.md).

### Running Cardano CLI Commands

Use the `cli` subcommand followed by regular `cardano-cli` arguments:

```bash
export CARDANO_NODE_SOCKET_PATH=~/.cardano/preview/node.socket
cardano cli query tip --testnet-magic 2
cardano cli query tip --testnet-magic=2 --socket-path=~/.cardano/preview/node.socket
```

## Additional Guides

- Hydra cluster setup and operations: [Hydra Guide](docs/hydra.md)
- Docker devnet with kuber, db-sync, Koios and Blockfrost: [Docker Devnet Guide](docs/devnet-docker.md)

## Binary Sources

- `cardano node` and `cardano cli` use official GitHub release assets from `IntersectMBO/cardano-node`.
- `cardano mithril` uses the official Mithril installer script.
- `cardano hydra` resolves binaries in this order:
  1. `ADAUP_HYDRA_NODE_PATH` and `ADAUP_HYDRA_TUI_PATH`
  2. Existing `hydra-node` and `hydra-tui` in `PATH`
  3. `ADAUP_HYDRA_DOWNLOAD_URL`
  4. GitHub Actions artifacts from `ADAUP_HYDRA_ACTIONS_RUN_URL`

For Hydra Actions artifacts, `adaup` resolves the artifact from the public GitHub Actions run and downloads it through a public `nightly.link` URL. The default bundled Hydra version `2.2.0` points to the successful release run `27418396480`.

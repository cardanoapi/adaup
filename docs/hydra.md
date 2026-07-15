# Hydra Guide

This guide covers the Hydra-related commands exposed by `adaup`.

## Overview

The `cardano hydra` command group helps you bootstrap local Hydra node credentials, generate runnable node scripts, launch nodes, inspect them with `hydra-tui`, and reset or prune local cluster data.

The current default Hydra version in `adaup` is `2.2.0`.

## Binary Resolution

`adaup` resolves Hydra binaries in this order:

1. `ADAUP_HYDRA_NODE_PATH` and `ADAUP_HYDRA_TUI_PATH`
2. Existing `hydra-node` and `hydra-tui` in `PATH`
3. `ADAUP_HYDRA_DOWNLOAD_URL`
4. GitHub Actions artifacts from `ADAUP_HYDRA_ACTIONS_RUN_URL`

For the bundled `2.2.0` default, `adaup` uses the successful release run `27418396480` when it needs a GitHub Actions artifact source.

When `adaup` uses a GitHub Actions artifact source, it resolves the artifact from the public run metadata and downloads it through a public `nightly.link` URL.

## Bootstrap a Cluster

Generate the folders and credentials for a Hydra cluster:

```bash
cardano hydra bootstrap preview 2
```

This creates `hydra-{n}` directories under `$HOME/.cardano/<network>/`.

You can also request a specific Hydra release:

```bash
cardano hydra bootstrap preview 2 --version 2.2.0
```

## Start Hydra Nodes

Start the first node:

```bash
cardano hydra node preview 0
```

Start the second node in another terminal:

```bash
cardano hydra node preview 1
```

Each node gets a generated run script at:

```text
~/.cardano/<network>/hydra-<index>/run.sh
```

You can also override the Hydra version when starting a node:

```bash
cardano hydra node preview 0 --version 2.2.0
```

## Open Hydra TUI

To interact with a running node through the terminal UI:

```bash
cardano hydra tui 0
```

## Reset Hydra Head Data

Stop the nodes, then reset their local data and refresh protocol parameters:

```bash
cardano hydra reset preview
```

## Prune a Hydra Cluster

To remove all local Hydra directories for a network:

```bash
cardano hydra prune preview
```

After pruning, run `bootstrap` again before starting nodes.

## Notes

- For official Hydra-supported networks such as `mainnet`, `preprod`, and `preview`, `adaup` now generates node commands using Hydra's `--network` flag.
- If an older generated `run.sh` is detected, `adaup` regenerates it so it matches the current Hydra invocation format.

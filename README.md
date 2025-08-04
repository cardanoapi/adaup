# Cardano Node Configuration

This repository contains the code to setup and configure cardano and hydra nodes for different networks.

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
    ├── preview
    │   └── ...
    ├── preprod
    │   └── ...
```

# Changelog

## Unreleased

### Added
- `cardano devnet --docker` (`up`, `down`, `status`, `smoke`): Conway devnet in docker with fresh genesis per run, governance-ready committee and constitution, kuber, cardano-db-sync + postgres and an anchor file server. See `docs/devnet-docker.md`.
- `cardano devnet smoke --docker`: governance smoke test and seeder covering DRep, delegation, committee and every proposal type.
- `ADAUP_DEVNET_*` environment overrides for the native devnet: slot length, epoch length, active slots coefficient, security parameter and starting protocol version.

### Fixed
- macOS: re-sign downloaded cardano-node binaries ad hoc, since the 11.1.2 macos-arm64 release is killed on launch otherwise.
- `python_requires` raised to 3.10, which the code already needed.

## Version 0.1.5

### Changed
- Moved Hydra management code from `src/adaup/__init__.py` to `src/adaup/commands/hydra.py`.
- Refactored Hydra-related functions into individual, more focused functions within `src/adaup/commands/hydra.py`.
- Removed non-download related functions from `src/adaup/download/hydra.py`.

### Added
- Add `reset` command to hydra to reset head and restart hydra without reseting keys.

## Version 0.1.4

### Fixed
- `958d9af` - Fix exec system call for cardano-node

## Version 0.1.3

### Fixed
- `ad87b17` - Bugfix: wrong config file being copied
- `c2bc6cf` - Fix cardano cli command

### Changed
- `6d10640` - Make 10.5.1 as default node version
- `8387bd1` - use exec to start cardano-node instead of subprocess

## Version 0.1.2

### Fixed
- `50c2d2c` - Fix release build

## Version 0.1.1

### Added
- `94af5d1` - Add workflow to publish package

## Version 0.1.0

### Added
- `692d7f9` - Initial version

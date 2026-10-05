# Changelog

## Version 0.5.0

### Added
- `cardano devnet up --docker --blockfrost` (or `ADAUP_DEVNET_BLOCKFROST=1`) also serves the devnet through the Blockfrost API at `http://127.0.0.1:8054`: blockfrost-ryo 6.8.0, built from its release commit for the host's architecture, over a db-sync of its own (`db-sync-blockfrost`, Postgres with pg_cardano at `127.0.0.1:5434`). It runs alongside db-sync and Koios on the same chain. See `docs/devnet-docker.md`.
- `ADAUP_DEVNET_BLOCKFROST_PORT`, `_BLOCKFROST_POSTGRES_PORT` and `_BLOCKFROST_IMAGE` (use your own ryo image, skipping the build); a `blockfrost` entry in `devnet.json`.

### Notes
- `--blockfrost` needs a whole-second `--slot-length`: Blockfrost types `slot_length` in `/genesis` and `/network/eras` as an integer, so 0.2 s slots would be served as `0`. `--slot-length 1 --active-slots-coeff 1 --epoch-length 60` keeps 60 s epochs with a block every second.
- The shared db-sync database is unchanged; ryo's `tx_out` layout (`consumed`, `force_tx_in`, no address table) lives only in the second one.

## Version 0.4.0

### Added
- `cardano devnet up --docker --koios` (or `ADAUP_DEVNET_KOIOS=1`) also serves the devnet through the Koios REST API at `http://127.0.0.1:8053/api/v1`: the gRest SQL (Koios v1.4.2, bundled) in the db-sync database, PostgREST, a cache-update loop and an nginx proxy. The first run builds a Postgres image with Koios's `pg_cardano` extension. See `docs/devnet-docker.md`.
- `ADAUP_DEVNET_KOIOS_PORT`, `_KOIOS_POSTGRES_BASE`, `_KOIOS_POSTGRES_IMAGE` (use your own Postgres with pg_cardano, skipping the build), `_PG_CARDANO_URL` (download mirror), `_POSTGREST_IMAGE` and `_KOIOS_PROXY_IMAGE` settings; a `koios` entry in `devnet.json`.

### Changed
- **Breaking:** db-sync on the docker devnet now runs with `tx_out.value: consumed`, `tx_out.use_address_table: true` and `tx_cbor: enable`, the settings Koios's SQL expects. The database schema differs from 0.3.0: addresses are in the `address` table (`tx_out.address_id`), and `tx_out.address` no longer exists. `tx_out.stake_address_id` is unchanged. To read an address, join `address` on `tx_out.address_id`. In `consumed` mode db-sync sets `tx_out.consumed_by_tx_id` on spent outputs and does not fill `tx_in`; Koios's balance functions rely on that column.

## Version 0.3.0

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

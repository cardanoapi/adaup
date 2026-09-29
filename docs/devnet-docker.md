# Docker Devnet

`cardano devnet --docker` runs an isolated Conway devnet in docker: one block-producing
`cardano-node` with full on-chain governance (protocol version 10), `kuber`, `cardano-db-sync`
with `postgres`, and a small HTTP server for governance anchors. The host needs only docker with
the compose plugin; every `cardano-cli` call runs inside the node image.

Genesis is regenerated on every `up` (`systemStart` = now), so the node database, db-sync state
and postgres volumes are recreated too.

## Commands

```bash
cardano devnet up --docker -d            # start, return once blocks are produced
cardano devnet up --docker -d --wait     # ... and wait until kuber and db-sync are healthy
cardano devnet up --docker               # start and follow logs; Ctrl+C removes the devnet
cardano devnet status --docker
cardano devnet smoke --docker            # governance smoke test / seeder, see below
cardano devnet down --docker             # remove containers, volumes and network
```

`up` options: `--dir`, `--slot-length`, `--epoch-length`, `--active-slots-coeff`,
`--security-param`, `--gov-action-lifetime`, `--drep-activity`, `--no-kuber`, `--no-dbsync`,
`--koios`, `-d/--detach`, `--wait`. Pass the same `--dir` to every command when not using the default.

## Environment

Command line flags win over environment variables, which win over the defaults.

| Variable | Default |
| --- | --- |
| `ADAUP_DEVNET_DIR` | `$CARDANO_HOME/devnet-docker` (`~/.cardano/devnet-docker`) |
| `ADAUP_DEVNET_PROJECT` | `adaup-devnet` (compose project and docker network name) |
| `ADAUP_DEVNET_SLOT_LENGTH` | `0.2` seconds |
| `ADAUP_DEVNET_EPOCH_LENGTH` | `300` slots (60 s epochs) |
| `ADAUP_DEVNET_ACTIVE_SLOTS_COEFF` | `0.25` (a block every ~0.8 s) |
| `ADAUP_DEVNET_SECURITY_PARAM` | `10` (Byron k and Shelley securityParam) |
| `ADAUP_DEVNET_PROTOCOL_MAJOR` | `10` |
| `ADAUP_DEVNET_LIVE_SECONDS` | `7200`, wall-clock time the two values below default to |
| `ADAUP_DEVNET_GOV_ACTION_LIFETIME` | `ceil(LIVE_SECONDS / epoch seconds)` epochs (120) |
| `ADAUP_DEVNET_DREP_ACTIVITY` | same as the lifetime |
| `ADAUP_DEVNET_DREP_DEPOSIT_ADA` / `_GOV_ACTION_DEPOSIT_ADA` | `500` / `1000` |
| `ADAUP_DEVNET_KEY_DEPOSIT_ADA` / `_POOL_DEPOSIT_ADA` | `2` / `500` |
| `ADAUP_DEVNET_COMMITTEE_SIZE` / `_THRESHOLD` / `_MIN_SIZE` / `_MAX_TERM` | `3` / `2/3` / `0` / `10000` epochs |
| `ADAUP_DEVNET_FAUCET_ADA` / `_POOL_STAKE_ADA` | `500000000` / `50000000` |
| `ADAUP_DEVNET_KUBER` / `_DBSYNC` / `_KOIOS` | `1` / `1` / `0` |
| `ADAUP_DEVNET_BIND` | `127.0.0.1` (host interface for published ports) |
| `ADAUP_DEVNET_KUBER_PORT` / `_POSTGRES_PORT` / `_ANCHOR_PORT` / `_KOIOS_PORT` | `8081` / `5433` / `8090` / `8053` |
| `ADAUP_DEVNET_POSTGRES_USER` / `_PASSWORD` / `_DB` | `postgres` / `postgres` / `cexplorer` |
| `ADAUP_DEVNET_NODE_IMAGE` / `_KUBER_IMAGE` / `_DBSYNC_IMAGE` / `_POSTGRES_IMAGE` | see `devnet_docker.py` |
| `ADAUP_DEVNET_KOIOS_POSTGRES_BASE` / `_POSTGREST_IMAGE` / `_KOIOS_PROXY_IMAGE` | `postgres:17-bookworm` / `postgrest/postgrest:v14.10` / `nginx:1.27-alpine` |
| `ADAUP_DEVNET_TIMEOUT` | `600` seconds for each wait |
| `ADAUP_DEVNET_IPFS_GATEWAYS` | empty (db-sync's default); comma-separated gateways for db-sync's `ipfs_gateway` |

The epoch length must be larger than the randomness stabilisation window `4k/f`.

## Genesis

Network magic 42 with `RequiresMagic`, Conway from epoch 0 at protocol version 10, experimental
hard forks disabled. The constitution has no guardrail script. The committee is made of
key-hash members whose cold and hot keys are generated into the output directory. Voting
thresholds are the mainnet ones. Genesis hashes are written into `config/cardano-node.json`.

## Output directory

```
docker-compose.yml, .env    rendered stack; plain `docker compose` works from here
devnet.json                 summary: addresses, pool id, committee hashes, ports, credentials
config/                     cardano-node.json, topology.json, *-genesis.json, db-sync-config.json
keys/faucet/                payment.{skey,vkey,addr}: funded enterprise address
keys/pool/                  cold, vrf, kes, opcert, byron delegate keys; pool.id
keys/pool-delegator/        payment and staking keys holding the pool's stake
keys/committee/ccN/         cc.cold.{skey,vkey}, cc.hot.{skey,vkey}
anchors/                    files served at http://anchors:8080/<name>
smoke/                      smoke test wallets, DReps, transactions and result.json
```

## Koios

`--koios` (or `ADAUP_DEVNET_KOIOS=1`) also serves the devnet through the [Koios](https://koios.rest)
REST API, at `http://127.0.0.1:8053/api/v1` (`http://koios/api/v1` in the network), so software
written against Koios can be tried on a chain you control. It needs db-sync.

```bash
cardano devnet up --docker -d --wait --koios
curl http://127.0.0.1:8053/api/v1/tip
```

It is the real gRest layer, not an imitation: Koios's SQL functions (`grest` schema, release
v1.4.2, bundled in the package) run in the db-sync database, and PostgREST publishes them behind a
small proxy that maps `/api/v1/<name>` to `/rpc/<name>`. Four extra services run under the `koios`
profile:

| Service | Does |
| --- | --- |
| `koios-init` | Creates the `pg_cardano` extension and the `grest` schema, fills `grest.genesis` from the devnet genesis files and applies the gRest SQL. Logs which files were applied and which failed. |
| `koios-cron` | Runs Koios's cache-update jobs (epoch info, stake distribution, active stake, pool history and info) every 10 s, as Koios does from cron every few minutes. |
| `postgrest` | PostgREST, configured as Koios configures it (`grest` schema, `web_anon`, 1000 rows). |
| `koios` | nginx: `/api/v1/<name>` to `/rpc/<name>`, `/health`. |

The first `up --koios` builds the Postgres image (`Dockerfile.postgres`, Debian Postgres 17 plus
Koios's prebuilt `pg_cardano` 1.2.0, downloaded from `share.koios.rest` and checked against a pinned
sha256), which takes a few minutes and needs the network; later runs reuse it. gRest's governance
and pool functions call `pg_cardano`, so the stock `postgres:17-alpine` cannot serve them.

Not started: the asset, address-book, submit and ogmios parts of a full Koios, and the jobs that need
a cardano-cli or a public registry (`cli-protocol-params`, `populate-next-epoch-nonce`, token
registry). The functions exist in the database, but endpoints that read what those jobs fill are
empty.

The gRest SQL is CC BY 4.0 (`assets/devnet/docker/koios/NOTICE`).

## db-sync configuration

`config/db-sync-config.json` is db-sync's `insert_options` with `tx_out.use_address_table: true`,
`tx_cbor: enable`, `ledger: enable` and `governance: enable`, plus off-chain pool and vote data.
The first two are what Koios's SQL indexes and reads; they are on for every devnet, with or
without `--koios`, so the database is the same shape either way. With the address table on,
`tx_out.stake_address_id` still exists but the address text is in `address`.

## Joining the stack from another compose project

Everything runs on the docker network `adaup-devnet` with these service names (`koios` only with `--koios`):

- `cardano-node`: node-to-node port 3001; socket at `/ipc/node.socket` in volume `adaup-devnet-ipc`
- `kuber`: `http://kuber:8081` (host `127.0.0.1:8081`)
- `postgres`: `postgres:5432`, database `cexplorer` (host `127.0.0.1:5433`)
- `db-sync`: fills `postgres`
- `anchors`: `http://anchors:8080` (host `127.0.0.1:8090`)

Node and genesis configuration is also in volume `adaup-devnet-config`.

```yaml
services:
  backend:
    environment:
      CARDANO_NODE_SOCKET_PATH: /ipc/node.socket
      DB_HOST: postgres
    volumes:
      - adaup-devnet-ipc:/ipc
      - adaup-devnet-config:/devnet-config:ro
    networks: [adaup-devnet]
networks:
  adaup-devnet:
    external: true
volumes:
  adaup-devnet-ipc:
    external: true
  adaup-devnet-config:
    external: true
```

## Governance smoke test

```bash
cardano devnet smoke --docker [--actions info,treasury,...] [--ratify treasury,parameter] [--no-wait-enactment]
```

It funds four wallets from the faucet, registers their stake keys, registers `drep1` and
`drep2` with anchors, updates `drep1`, delegates votes to `drep1`, always-abstain,
always-no-confidence and `drep2`, retires `drep2`, and authorises the committee hot keys.
It then submits one proposal per action in `--actions` (default: all of `info`, `treasury`,
`parameter`, `hardfork`, `no-confidence`, `committee`, `constitution`) and votes on each as
DRep, SPO (genesis pool cold key) and CC wherever the ledger allows. Actions in `--ratify`
(default `treasury,parameter,committee,constitution`) get yes votes, the others no votes, so
by default the hard fork and no-confidence actions stay unratified. Unless
`--no-wait-enactment` is given it waits for the ratified actions to be enacted.

Setup steps check the ledger first, so the command can be run repeatedly; each run adds a new
set of proposals that stay live for the governance action lifetime. `ADAUP_DEVNET_SMOKE_ACTIONS`
and `ADAUP_DEVNET_SMOKE_RATIFY` set the same lists. Proposal ids, timings and db-sync row counts
are written to `smoke/result.json`.

## Notes

- db-sync runs with `--force-indexes` (without it, it deadlocks on a fresh chain that is near
  the tip from the first block) and `--allow-private-offchain-urls` (anchors are served on the
  private docker network).
- db-sync fetches off-chain anchor data in batches every 5 minutes, so `off_chain_vote_*` rows
  lag the on-chain rows by up to that long.
- Enactment takes two to three epoch boundaries after submission, plus one epoch for each
  additional delaying action (committee, constitution, hard fork, no confidence) ratified at
  the same time.

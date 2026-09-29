#!/bin/bash
# One-shot: deploy the gRest schema and RPC functions into the db-sync database.
#
# Mirrors what Koios's setup-grest.sh does (-q): basics.sql, the pg_cardano
# extension, the grest.genesis row, then every files/grest/rpc/**/*.sql in path
# order. Every file is tried and failures are listed, then the script exits
# non-zero unless KOIOS_ALLOW_FAILED=1.
#
# Environment: PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE, GENESIS_DIR.
set -uo pipefail

GREST=/koios/grest
GENESIS_DIR=${GENESIS_DIR:-/config}
psql_q() { psql -v ON_ERROR_STOP=1 -X -q "$@"; }

echo "Waiting for db-sync to insert its first block..."
until [ "$(psql -X -tAc 'select 1 from block where block_no is not null limit 1' 2>/dev/null)" = 1 ]; do sleep 2; done

echo "Creating the pg_cardano extension and the grest schema..."
psql_q -c 'CREATE EXTENSION IF NOT EXISTS pg_cardano;' || exit 1
psql_q -f "$GREST/rpc/db-scripts/basics.sql" || exit 1

echo "Writing grest.genesis from $GENESIS_DIR..."
sg="$GENESIS_DIR/shelley-genesis.json"
ag="$(jq -c . "$GENESIS_DIR/alonzo-genesis.json")"
# One value per line: `read` over a tab-separated line would merge empty fields
# and shift every later value into the wrong column.
mapfile -t values < <(jq -r '.activeSlotsCoeff, .updateQuorum, .networkId, .maxLovelaceSupply, .networkMagic,
  .epochLength, .systemStart, .slotsPerKESPeriod, .slotLength, .maxKESEvolutions, .securityParam' "$sg")
[ "${#values[@]}" -eq 11 ] || { echo "shelley genesis yielded ${#values[@]} values, expected 11" >&2; exit 1; }
psql_q -v alonzo="$ag" \
  -v v0="${values[0]}" -v v1="${values[1]}" -v v2="${values[2]}" -v v3="${values[3]}" -v v4="${values[4]}" \
  -v v5="${values[5]}" -v v6="${values[6]}" -v v7="${values[7]}" -v v8="${values[8]}" -v v9="${values[9]}" \
  -v v10="${values[10]}" <<'SQL' || exit 1
TRUNCATE grest.genesis;
INSERT INTO grest.genesis VALUES (:'v4', :'v2', :'v0', :'v1', :'v3', :'v5', :'v6', :'v7', :'v8', :'v9', :'v10', :'alonzo');
SQL

ok=0
failed=()
while IFS= read -r file; do
  if output=$(psql_q -f "$file" 2>&1); then
    ok=$((ok + 1))
  else
    failed+=("${file#$GREST/rpc/}")
    echo "  FAILED ${file#$GREST/rpc/}: $(printf '%s' "$output" | grep -m1 -E 'ERROR' || echo "$output" | head -1)"
  fi
done < <(find "$GREST/rpc" -name '*.sql' ! -path '*/db-scripts/*' | LC_ALL=C sort)

echo "gRest deployed: $ok files applied, ${#failed[@]} failed."
psql_q -c "NOTIFY pgrst, 'reload schema'" || true
# A partial deploy must not look healthy: PostgREST and the cache loop wait for
# this container to succeed. KOIOS_ALLOW_FAILED=1 accepts it.
if [ "${#failed[@]}" -gt 0 ] && [ "${KOIOS_ALLOW_FAILED:-0}" != 1 ]; then
  echo "Failing: ${failed[*]}" >&2
  exit 1
fi

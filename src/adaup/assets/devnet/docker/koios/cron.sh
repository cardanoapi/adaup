#!/bin/bash
# Keeps gRest's cache tables current. Koios runs these jobs from cron every 5-15
# minutes; a devnet epoch lasts about a minute, so they run in a short loop.
#
# The job scripts are Koios's own (files/grest/cron/jobs). They call
# `psql ${DB_NAME}`, so DB_NAME is pointed at this devnet's database.
#
# Environment: PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE, KOIOS_CRON_INTERVAL.
set -uo pipefail

JOBS=/koios/grest/cron
INTERVAL=${KOIOS_CRON_INTERVAL:-10}

while true; do
  for job in epoch-info-cache-update stake-distribution-update active-stake-cache-update \
             pool-history-cache-update pool-info-cache-update; do
    sed "s/^DB_NAME=.*/DB_NAME=${PGDATABASE}/" "$JOBS/$job.sh" | bash 2>&1 | sed "s/^/[$job] /"
  done
  sleep "$INTERVAL"
done

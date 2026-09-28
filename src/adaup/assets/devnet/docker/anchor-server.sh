#!/usr/bin/env bash
# Minimal read-only HTTP/1.0 file server for governance anchor documents.
# socat runs one instance per connection with the socket on stdin/stdout.
# Only flat file names made of [A-Za-z0-9._-] are served, so requests can
# never leave ANCHOR_ROOT.

set -u
ROOT="${ANCHOR_ROOT:-/www}"

respond() {
  local status="$1" type="$2" file="${3:-}" length=0
  if [[ -n "$file" ]]; then
    length=$(stat -c %s "$file")
  fi
  printf 'HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %s\r\nConnection: close\r\n\r\n' \
    "$status" "$type" "$length"
  if [[ -n "$file" && "$METHOD" != "HEAD" ]]; then
    cat "$file"
  fi
}

IFS=$' \r' read -r METHOD TARGET _ || exit 0
# Drain the request headers.
while IFS=$'\r' read -r line && [[ -n "$line" ]]; do :; done

TARGET="${TARGET%%\?*}"
NAME="${TARGET#/}"

if [[ "$METHOD" != "GET" && "$METHOD" != "HEAD" ]]; then
  respond "405 Method Not Allowed" "text/plain"
elif [[ -z "$NAME" ]]; then
  printf 'HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 3\r\nConnection: close\r\n\r\nok\n'
elif [[ ! "$NAME" =~ ^[A-Za-z0-9._-]+$ || "$NAME" == .* || ! -f "$ROOT/$NAME" ]]; then
  respond "404 Not Found" "text/plain"
else
  case "$NAME" in
    *.jsonld|*.json) TYPE="application/json" ;;
    *) TYPE="application/octet-stream" ;;
  esac
  respond "200 OK" "$TYPE" "$ROOT/$NAME"
fi

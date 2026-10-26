#!/bin/sh
set -eu
state=${FITCHECK_BACKUP_STATE_DIR:-/state}
directory=${FITCHECK_BACKUP_DIR:-/backups}
mkdir -p "$state" "$directory"
sleep_pid=
trap 'if [ -n "$sleep_pid" ]; then kill "$sleep_pid" 2>/dev/null || true; fi; exit 0' TERM INT
due() {
  value=0
  if [ -f "$state/$1.timestamp" ]; then value=$(cat "$state/$1.timestamp"); fi
  case "$value" in ''|*[!0-9]*) value=0 ;; esac
  [ "$(($(date -u +%s)-value))" -ge "$2" ]
}
while :; do
  if due backup 86400; then
    if sh /ops/backup.sh backup; then sh /ops/backup.sh prune || true; fi
  fi
  if due restore 604800; then
    archive=$(find "$directory" -maxdepth 1 -type f -name 'fitcheck-*.dump' -printf '%f\n' | sort | tail -1)
    if [ -n "$archive" ]; then sh /ops/backup.sh restore-check "$archive" || true; fi
  fi
  sleep 3600 & sleep_pid=$!
  wait "$sleep_pid" || true
  sleep_pid=
done

#!/bin/sh
# Credentials come from a mounted pg_service.conf/PGPASSFILE, never arguments.
set -eu
umask 077
directory=${FITCHECK_BACKUP_DIR:-/backups}
state=${FITCHECK_BACKUP_STATE_DIR:-/state}
mkdir -p "$directory" "$state"
export PGSERVICE=${PGSERVICE:-fitcheck}
export PGCONNECT_TIMEOUT=5
export PGAPPNAME=fitcheck-backup
failure() { printf '{"event":"backup_failed","stage":"%s"}\n' "$1" >&2; exit 1; }
marker() {
  temporary="$state/.$1.$$"
  date -u +%s > "$temporary"
  chmod 644 "$temporary"
  mv "$temporary" "$state/$1.timestamp"
}
case "${1:-}" in
  backup)
    name="fitcheck-$(date -u +%Y%m%dT%H%M%SZ)-$$.dump"
    temporary=$(mktemp "$directory/.partial-XXXXXX")
    trap 'rm -f "$temporary"' EXIT
    trap 'exit 143' HUP INT TERM
    pg_dump --no-password --format=custom --file="$temporary" 2>/dev/null || failure dump
    pg_restore --list "$temporary" >/dev/null 2>&1 || failure archive_validation
    mv "$temporary" "$directory/$name"
    (cd "$directory"; sha256sum "$name" > "$name.sha256") || failure checksum
    marker backup
    printf '{"event":"backup_succeeded","archive":"%s"}\n' "$name"
    ;;
  restore-check)
    archive=${2:-}
    case "$archive" in fitcheck-*.dump) ;; *) failure archive_name ;; esac
    case "$archive" in *[!a-zA-Z0-9._-]*) failure archive_name ;; esac
    test -f "$directory/$archive" && test ! -L "$directory/$archive" || failure archive_missing
    (cd "$directory"; sha256sum --check "$archive.sha256" >/dev/null 2>&1) || failure checksum
    # The target is always a new disposable DB, never a caller-supplied database.
    target="fitcheck_restore_check_$(date -u +%Y%m%d%H%M%S)_$$"
    export PGSERVICE=${FITCHECK_RESTORE_SERVICE:-fitcheck_restore}
    unset PGDATABASE
    created=false
    cleanup() {
      if [ "$created" = true ]; then dropdb --no-password "$target" >/dev/null 2>&1 || true; fi
    }
    trap cleanup EXIT
    trap 'exit 143' HUP INT TERM
    createdb --no-password --maintenance-db=postgres "$target" >/dev/null 2>&1 || failure create_disposable_database
    created=true
    pg_restore --no-password --exit-on-error --single-transaction --no-owner --no-acl --dbname="$target" "$directory/$archive" >/dev/null 2>&1 || failure restore
    # SQL validates the restored app graph without printing any private rows.
    psql --no-password --dbname="$target" --set=ON_ERROR_STOP=1 --no-psqlrc --tuples-only --no-align --command="SELECT version_num FROM alembic_version" > "$state/.revision.$$" 2>/dev/null || failure schema
    revision=$(cat "$state/.revision.$$"); rm -f "$state/.revision.$$"
    case "$revision" in ''|*[!a-zA-Z0-9_]*) failure revision ;; esac
    psql --no-password --dbname="$target" --set=ON_ERROR_STOP=1 --no-psqlrc --file="${FITCHECK_RESTORE_VERIFY_SQL:-/ops/verify.sql}" >/dev/null 2>&1 || failure graph
    dropdb --no-password "$target" >/dev/null 2>&1 || failure remove_disposable_database
    created=false
    marker restore
    printf '{"event":"restore_check_succeeded","revision":"%s","archive":"%s"}\n' "$revision" "$archive"
    ;;
  prune)
    days=${FITCHECK_BACKUP_RETENTION_DAYS:-14}
    case "$days" in ''|*[!0-9]*) failure retention ;; esac
    [ "$days" -ge 7 ] && [ "$days" -le 3650 ] || failure retention
    test -f "$state/backup.timestamp" || failure no_successful_backup
    now=$(date -u +%s); last=$(cat "$state/backup.timestamp")
    [ "$((now-last))" -lt 86400 ] || failure no_recent_backup
    find "$directory" -maxdepth 1 -type f -name 'fitcheck-*.dump' -mtime "+$days" -exec sh -c 'for archive do rm -f "$archive" "$archive.sha256"; done' sh {} +
    printf '{"event":"backup_retention_completed"}\n'
    ;;
  *) printf 'Usage: backup.sh {backup|restore-check ARCHIVE|prune}\n' >&2; exit 2 ;;
esac

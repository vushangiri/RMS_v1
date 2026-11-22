#!/bin/sh
set -eu
umask 077

directory=/backups
prefix="rms-${PGDATABASE:?Set PGDATABASE}"
daily_pattern="$prefix-daily-*.dump"

recent_daily() {
    [ -n "$(find "$directory" -maxdepth 1 -type f -name "$daily_pattern" -mmin "-$1" -print -quit)" ]
}

write_dump() (
    mode=$1
    exec 9>"$directory/.rms-backup.lock"
    flock 9

    # A waiting scheduler may find another daily run already finished.
    if [ "$mode" = daily ] && recent_daily 1440; then
        return 0
    fi

    find "$directory" -maxdepth 1 -type f -name '.rms-partial-*' -exec rm -f {} +
    temporary=$(mktemp "$directory/.rms-partial-XXXXXXXX")
    trap 'rm -f "$temporary"' EXIT
    trap 'exit 1' HUP INT TERM
    filename="$prefix-$mode-$(date -u +%Y%m%dT%H%M%SZ)-${temporary##*-}.dump"

    pg_dump --no-password --format=custom --file="$temporary"
    pg_restore --list "$temporary" >/dev/null
    pg_restore --exit-on-error --file=/dev/null "$temporary"
    touch "$temporary"
    sync "$temporary"
    mv "$temporary" "$directory/$filename"
    sync "$directory"
    if [ "$mode" = daily ]; then
        printf '%s\n' "$filename"
        find "$directory" -maxdepth 1 -type f -name "$daily_pattern" -mtime +29 -exec rm -f {} +
    else
        printf '%s/%s\n' "${RMS_BACKUP_LOCATION%/}" "$filename"
    fi
)

mode=${1:-schedule}
case "$mode" in
    schedule|once)
        chmod 700 "$directory"
        owner=$(stat -c '%u:%g' "$directory")
        if [ "$(id -u)" -eq 0 ] && [ "${owner%%:*}" -ne 0 ]; then
            exec su-exec "$owner" sh "$0" "$mode"
        fi
        ;;
    daily-run)
        write_dump daily
        exit
        ;;
    health)
        recent_daily 1560
        exit
        ;;
    *)
        echo "Usage: $0 schedule|once|health" >&2
        exit 2
        ;;
esac

if [ "$mode" = once ]; then
    write_dump manual
    exit
fi

pause() {
    sleep "$1" &
    wait "$!"
}

trap 'exit 0' HUP INT TERM
while :; do
    if ! recent_daily 1440; then
        # Keep errexit enabled inside a separate shell so a failed dump cannot be published.
        if ! sh "$0" daily-run; then
            echo "Daily RMS backup failed. Retrying in five minutes." >&2
            pause 300
            continue
        fi
    fi
    pause 60
done

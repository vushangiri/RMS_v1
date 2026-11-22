#!/bin/sh
set -eu
archive=${1:?Supply a custom-format backup}
target=${2:?Supply a new database name beginning rms_restore_}
case "$target" in
    rms_restore_?*) ;;
    *) echo "Restore targets must begin rms_restore_ and include a suffix." >&2; exit 2 ;;
esac
case "$target" in
    *[!a-z0-9_]*) echo "Use lowercase letters, digits and underscores in the target." >&2; exit 2 ;;
esac
if [ "${#target}" -gt 63 ]; then
    echo "The target database name must be at most 63 characters." >&2
    exit 2
fi

docker compose exec -T db pg_restore --list < "$archive" >/dev/null
docker compose exec -T db createdb -U rms "$target"
docker compose exec -T db pg_restore -U rms --no-owner --single-transaction --exit-on-error -d "$target" < "$archive"
docker compose exec -T db psql -X -v ON_ERROR_STOP=1 -U rms -d "$target" \
    -c 'select version_num from alembic_version' \
    -c 'select count(*) from event'

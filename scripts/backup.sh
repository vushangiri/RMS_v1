#!/bin/sh
set -eu
# The backup service writes to its host bind mount, including during a one-off run.
docker compose run --rm -T --no-deps backup once

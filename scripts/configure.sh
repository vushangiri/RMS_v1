#!/bin/sh
set -eu
umask 077
(set -C; { echo "POSTGRES_PASSWORD=$(openssl rand -hex 30)"; echo "SECRET_KEY=$(openssl rand -hex 48)"; echo COOKIE_SECURE=1; echo RMS_PORT=8090; } > .env)
mkdir -p backups

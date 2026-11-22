# Ubuntu VPS deployment

## Fresh project

Install Docker Engine and the Compose v2 plugin, and use a root-owned or operator-owned directory for the project. PostgreSQL and Gunicorn have no published ports. The Compose proxy listens on loopback. For initial testing, use HTTP over an SSH tunnel. You can add a domain and HTTPS later.

```sh
sh scripts/configure.sh
# For HTTP testing, set COOKIE_SECURE=0 in .env before starting Compose.
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
docker compose logs migrate
curl --fail http://127.0.0.1:8090/health
docker compose exec app flask --app wsgi:app init-admin
sh scripts/backup.sh
```

Expected health response is `{"ready":true}`. A completed migration container has exit code 0. Keep the generated .env file private. Use generated hexadecimal database passwords because the connection URL embeds this value. Change RMS_PORT before startup if another application owns 8090, then use the same remote port in the commands below.

## HTTP testing without a domain

Set `COOKIE_SECURE=0` in the VPS project’s `.env` for HTTP testing. If RMS is already running, apply the change with `docker compose up -d --no-deps app`. On the VPS itself, open `http://127.0.0.1:8090` or use the health check above.

From your own computer, open an SSH tunnel using the VPS IP address. Keep the SSH session running while using RMS.

```sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8090:127.0.0.1:8090 your-user@VPS_IP
```

Open [http://127.0.0.1:8090](http://127.0.0.1:8090) on your computer and sign in. If your computer already uses port 8090, change the first port in the tunnel command to 8091 and open `http://127.0.0.1:8091`. SSH encrypts the connection to the VPS. Port 8090 stays on loopback, so this setup needs neither a public HTTP port nor a domain.

### Direct IP access for a restricted test

For direct browser access, set these values in the VPS project’s `.env`. Restrict inbound TCP 8090 to your own public IP in the VPS provider’s firewall before publishing the port. Plain HTTP sends credentials and ledger data without encryption, so use the SSH tunnel for real data.

```dotenv
RMS_BIND_ADDRESS=0.0.0.0
RMS_PORT=8090
COOKIE_SECURE=0
```

Apply the changes from the VPS project directory.

```sh
docker compose up -d --no-deps --wait app
docker compose up -d --no-deps --force-recreate --wait proxy
docker compose port proxy 80
```

The last command should show `0.0.0.0:8090`. Then browse to `http://VPS_IP:8090`. If it still times out, check the provider firewall and use the VPS’s public IP. To return to tunnel-only access, remove `RMS_BIND_ADDRESS` from `.env` and recreate the proxy.

## Host Nginx and TLS

When switching to HTTPS, remove any direct-access `RMS_BIND_ADDRESS` override and recreate the proxy. Set `COOKIE_SECURE=1` in `.env` and apply it with `docker compose up -d --no-deps app` before using the public URL.

Point your domain at the server. Add this site on the existing host Nginx, substituting the domain and the selected loopback port. The container's own proxy configuration is already included.

```nginx
server {
    listen 80;
    server_name rms.example.com;
    client_max_body_size 6m;
    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Validate the host configuration with `sudo nginx -t`, reload it, then use your certificate manager. With Certbot and the Nginx plugin installed, run `sudo certbot --nginx -d rms.example.com --redirect` for the actual domain. Verify HTTPS login, logout, one trial receipt and renewal with `sudo certbot renew --dry-run`. Run the trial in a separate Compose project and volume from the restaurant ledger. The app's installable PWA requires HTTPS or localhost. Offline navigation displays a reconnect page; entries must reach the server to be recorded.

## Daily database backups

Compose starts the `backup` service after migrations. It creates a custom-format PostgreSQL dump on the first run and when the latest daily dump is 24 hours old. It retries failed jobs after five minutes. The job validates the archive and reads it end to end before publishing it. It keeps daily dumps for 30 days. On-demand dumps made with `sh scripts/backup.sh` are kept until you remove them.

The default destination is the host's `./backups` directory, separate from the Docker database volume. To use another local disk, add `RMS_BACKUP_DIR=/path/to/existing/private-directory` to `.env` before starting Compose. The directory is restricted to its owner. Backups contain users, audit records, receipt images, and closing snapshots. A disk or VPS failure can still affect both local copies, so keep an encrypted copy of the backup directory and deployment configuration off the VPS. With daily backups alone, changes since the last successful dump may need to be re-entered.

```sh
docker compose ps backup
docker compose logs --tail=30 backup
sh scripts/backup.sh
```

Use the database name and UTC timestamp in each filename to select a dump. Check that a new daily file appears within 24 hours. The backup service reports unhealthy if its latest daily file is more than 26 hours old.

### Restore drill

Restore to a fresh database name beginning with `rms_restore_`. Existing databases are protected by PostgreSQL's create-database check.

```sh
sh scripts/restore.sh /path/to/backup.dump rms_restore_check
docker compose exec db psql -U rms -d rms_restore_check -c 'select coalesce(sum(amount),0) from posting'
```

The posting sum should be zero. Compare record counts, actual drawer balances, outstanding credit, receipts, and the latest closing snapshot with the original ledger. Keep the backup files during the drill.

### Recover after volume loss

Stop the old app, proxy, and backup service before switching so the old database cannot receive writes. Use a separate Compose project for a clean database volume. Leave the failed volume available for investigation.

```sh
docker compose stop app proxy backup
docker compose -p rms-recovery up -d --wait db
COMPOSE_PROJECT_NAME=rms-recovery sh scripts/restore.sh /path/to/backup.dump rms_restore_live
docker compose -p rms-recovery exec db psql -U rms -d rms_restore_live -c 'delete from login_session'
```

Verify the restored data as in the drill. Set `RMS_DB_NAME=rms_restore_live` in `.env` so the app, migration job, and backup service use the restored database. Start the recovery project with `docker compose -p rms-recovery up -d --build`, check the app health and latest closing, and take a new manual backup. Keep using `-p rms-recovery` for subsequent commands on that deployment.

## Updates

Back up before upgrading. Keep .env, the project name and the database volume. Stop web writes with `docker compose stop app proxy`, install the new source, rebuild and run the new migration with `docker compose run --rm migrate`. Start services, inspect logs, check the last closing and sign in. Never use `docker compose down -v` on restaurant data. If a release changes the schema incompatibly, restore the pre-upgrade dump to another database and run the matching previous image.

The application uses its own migration family beginning at ledger_01. An earlier RMS installation needs an explicit data mapping and reconciliation before import. This package does not perform an in-place conversion of earlier data.

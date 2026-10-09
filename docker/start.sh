#!/bin/bash
set -e

# Ensure directories exist and have proper permissions
mkdir -p /var/log/supervisor /var/run/postgresql /var/lib/postgresql/data
chown -R postgres:postgres /var/run/postgresql /var/lib/postgresql/data
chmod 2775 /var/run/postgresql

# Initialize Postgres if data directory is empty
if [ -z "$(ls -A /var/lib/postgresql/data)" ]; then
    echo "Initializing Postgres database..."
    su - postgres -c "/usr/lib/postgresql/15/bin/initdb -D /var/lib/postgresql/data"
    
    # Enable TimescaleDB in postgresql.conf
    echo "shared_preload_libraries = 'timescaledb'" >> /var/lib/postgresql/data/postgresql.conf
    
    # Restrict connection access to local loopback (in-container)
    echo "listen_addresses = '127.0.0.1,localhost'" >> /var/lib/postgresql/data/postgresql.conf
    echo "host all all 127.0.0.1/32 md5" >> /var/lib/postgresql/data/pg_hba.conf
    echo "host all all ::1/128 md5" >> /var/lib/postgresql/data/pg_hba.conf
    
    # Start PG temporarily to run init script
    su - postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/data -w start"
    
    # Create required DB and users from env vars
    su - postgres -c "psql -c \"CREATE USER ${DB_USER:-postgres} WITH PASSWORD '${DB_PASSWORD:-postgres}';\"" || true
    su - postgres -c "psql -c \"CREATE DATABASE \\\"NexusQuantDB\\\" OWNER ${DB_USER:-postgres};\"" || true
    su - postgres -c "psql -c \"ALTER ROLE ${DB_USER:-postgres} SUPERUSER;\"" || true
    su - postgres -c "psql -d NexusQuantDB -c \"CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;\"" || true

    # Run versioned schema migrations
    if [ -f "/app/scripts/migrate.py" ]; then
        echo "Running schema migrations via migrate.py..."
        python3 /app/scripts/migrate.py || true
    fi
    
    # Stop PG
    su - postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/data -m fast -w stop"
fi

# Force locale fix in existing postgresql.conf if it exists
if [ -f "/var/lib/postgresql/data/postgresql.conf" ]; then
    echo "Fixing locales in postgresql.conf..."
    sed -i "s/lc_messages = 'en_US.utf8'/lc_messages = 'C.UTF-8'/g" /var/lib/postgresql/data/postgresql.conf
    sed -i "s/lc_monetary = 'en_US.utf8'/lc_monetary = 'C.UTF-8'/g" /var/lib/postgresql/data/postgresql.conf
    sed -i "s/lc_numeric = 'en_US.utf8'/lc_numeric = 'C.UTF-8'/g" /var/lib/postgresql/data/postgresql.conf
    sed -i "s/lc_time = 'en_US.utf8'/lc_time = 'C.UTF-8'/g" /var/lib/postgresql/data/postgresql.conf
fi

echo "Starting supervisord..."
exec supervisord -c /supervisord.conf

#!/bin/sh
if [ "$DATABASE" = "mssql" ] && [ "$SERVICE_NAME" = "backend" ]
then
    echo "Waiting for MSSQL..."

    # Wait until MSSQL is ready to accept connections
    until /opt/mssql-tools18/bin/sqlcmd -S $APP_DB_SERVER -U $APP_DB_USERNAME -P $APP_DB_PASSWORD -C -Q "SELECT 1" > /dev/null 2>&1
    do
        echo "MSSQL is unavailable - sleeping"
        sleep 5
    done

    echo "MSSQL is up - executing initialization"

    # Create database if it doesn't exist
    /opt/mssql-tools18/bin/sqlcmd -S $APP_DB_SERVER -U $APP_DB_USERNAME -P $APP_DB_PASSWORD -C -Q "
    IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'$APP_DB_DATABASE')
    BEGIN
        CREATE DATABASE [$APP_DB_DATABASE];
    END;
    "

    echo "Database $APP_DB_DATABASE created"

    # Create a new login and user with appropriate permissions
    /opt/mssql-tools18/bin/sqlcmd -S $APP_DB_SERVER -U $APP_DB_USERNAME -P $APP_DB_PASSWORD -C -d $APP_DB_DATABASE -Q "
    IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = N'$APP_DB_APP_USERNAME')
    BEGIN
        CREATE LOGIN [$APP_DB_APP_USERNAME] WITH PASSWORD = '$APP_DB_APP_PASSWORD';
    END;
    IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = N'$APP_DB_APP_USERNAME')
    BEGIN
        CREATE USER [$APP_DB_APP_USERNAME] FOR LOGIN [$APP_DB_APP_USERNAME];
        ALTER ROLE db_owner ADD MEMBER [$APP_DB_APP_USERNAME];
    END;
    "

    echo "User $APP_DB_APP_USERNAME created"
fi

if [ "$SERVICE_NAME" = "backend" ]
then
    echo "Migrating database..."
    flask --app manage.py db upgrade
    echo "Seeding users..."
    python3.11 manage.py seed_db
    echo "Seeding the database..."
    python3.11 manage.py seed_data_db

if [ "$FLASK_DEBUG" = "1" ]
then
    python3.11 -m debugpy --listen 0.0.0.0:$DEBUG_PORT manage.py run -h 0.0.0.0
else
    # gunicorn --access-logfile=/var/log/gunicorn/access.log --error-logfile=/var/log/gunicorn/error.log --preload -k gevent -w 1 -b 0.0.0.0:5000 manage:app
    gunicorn -c gunicorn_config.py manage:app
fi

else

if [ "$FLASK_DEBUG" = "1" ]
then
    python3.11 -m debugpy --listen 0.0.0.0:$DEBUG_PORT manage.py run_worker
else
    python3.11 manage.py run_worker
fi

fi

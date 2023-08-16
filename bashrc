#bin/bash

export PATH="/home/fedow/.local/bin:$PATH"
alias collect="poetry run python3 manage.py collectstatic --noinput"
alias rsp="poetry run python3 manage.py runserver 0.0.0.0:8000"
alias rsp80="poetry run python3 manage.py runserver 0.0.0.0:80"
alias guni="poetry run gunicorn fedowallet_django.wsgi --log-level=debug --log-file /fedow/www/gunicorn.logs -w 3 -b 0.0.0.0:8000"

load_sql() {
export PGPASSWORD=$POSTGRES_PASSWORD
export PGUSER=$POSTGRES_USER
export PGHOST=$POSTGRES_HOST

psql --dbname $POSTGRES_DB -f $1

echo "SQL file loaded : $1"
}

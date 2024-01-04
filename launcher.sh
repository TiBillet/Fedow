#!/bin/bash
set -e


#curl -sSL https://install.python-poetry.org | python3
export PATH="/home/fedow/.local/bin:$PATH"
poetry install
echo "Poetry install ok"

#sleep infinity

poetry run python3 manage.py migrate
poetry run python3 manage.py collectstatic --noinput
echo "Run GUNICORN"
poetry run gunicorn fedowallet_django.wsgi --log-level=info --log-file /home/fedow/Fedow/logs/gunicorn.logs -w 5 -b 0.0.0.0:8000



#!/bin/bash
set -e

#poetry install
#echo "Poetry install ok"

poetry run python3 manage.py migrate
poetry run python3 manage.py collectstatic --noinput
poetry run python3 manage.py install
poetry run python3 manage.py runserver 0.0.0.0:80

#echo "Run GUNICORN"
#poetry run gunicorn fedowallet_django.wsgi --log-level=debug --log-file /fedow/www/gunicorn.logs -w 3 -b 0.0.0.0:8000
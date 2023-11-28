#!/bin/bash
#set -e
# test si ça crash bien :
#cat non_existent_file.txt
#echo "caca"

rm db.sqlite3
rm fedow_core/migrations/00*
poetry run ./manage.py makemigrations
poetry run ./manage.py migrate
poetry run ./manage.py install
poetry run ./manage.py runserver 0.0.0.0:80

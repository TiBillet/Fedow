#!/bin/bash
#set -e
# test si ça crash bien :
#cat non_existent_file.txt
#echo "caca"

rm db.sqlite3
rm fedow_core/migrations/00*
./manage.py makemigrations
./manage.py migrate
./manage.py install
./manage.py runserver_plus 0.0.0.0:80

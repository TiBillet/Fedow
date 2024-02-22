#!/bin/bash
set -e
# test si ça crash bien :
#cat non_existent_file.txt
#echo "devrait pas passer"

flush_db(){
  poetry run ./manage.py flush --no-input
  poetry run ./manage.py install
  poetry run ./manage.py createsuperuser --noinput --username root --email root@root.root
  poetry run ./manage.py shell_plus -c "User=get_user_model();root=User.objects.get(username='root');root.set_password('root');root.save()"
  poetry run ./manage.py runserver 0.0.0.0:80
}

#while getopts ":d" option; do
#  case $option in
#  d) # delete migrations
#    delete_migrations
#    flush_db
#    exit
#    ;;
#  \?) # Invalid option
#    echo "Error: Invalid option"
#    exit
#    ;;
#  esac
#done


flush_db


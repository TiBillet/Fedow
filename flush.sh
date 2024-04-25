#!/bin/bash
set -e
# test si ça crash bien :
#cat non_existent_file.txt
#echo "devrait pas passer"
# /bin/bash
if [ "$TEST" = "1" ]
then
  poetry run ./manage.py flush --no-input
  poetry run ./manage.py install
  poetry run ./manage.py createsuperuser --noinput --username root --email root@root.root
  poetry run ./manage.py shell_plus -c "User=get_user_model();root=User.objects.get(username='root');root.set_password('root');root.save()"
  echo "start dev server : https://fedow.tibillet.localhost/dashboard/"
  poetry run ./manage.py runserver 0.0.0.0:8000

else
    echo "TEST environment variable is not set"
fi




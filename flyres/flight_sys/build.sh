#!/bin/bash
set -o errexit

python flight_sys/manage.py collectstatic --no-input
python flight_sys/manage.py migrate

if [ "$DJANGO_CREATEUSER" == "1" ]; then 
    python flight_sys/manage.py createsuperuser --noinput
fi

python flight_sys/manage.py runserver 0.0.0.0:$PORT
#!/bin/bash
set -o errexit

python flyres/flight_sys/manage.py collectstatic --no-input
python flyres/flight_sys/manage.py migrate

if [ "$DJANGO_CREATEUSER" == "1" ]; then 
    python flyres/flight_sys/manage.py createsuperuser --noinput
fi

python flyres/flight_sys/manage.py runserver 0.0.0.0:$PORT
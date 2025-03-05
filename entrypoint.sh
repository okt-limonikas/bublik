#!/bin/bash

echo "Collect Static Files"
python manage.py collectstatic --noinput

echo "Apply Database Migrations"
python manage.py makemigrations
python manage.py migrate

# Create superuser
echo "Creating Superuser"
python manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
SUPERUSER_EMAIL = '${DJANGO_SUPERUSER_EMAIL:-admin@bublik.com}'
SUPERUSER_PASSWORD = '${DJANGO_SUPERUSER_PASSWORD:-admin}'
if not User.objects.filter(email=SUPERUSER_EMAIL).exists():
    User.objects.create_superuser(
        email=SUPERUSER_EMAIL,
        password=SUPERUSER_PASSWORD,
        is_active=True
    )
    print(f'Superuser created with email: {SUPERUSER_EMAIL}')
else:
    print(f'Superuser with email {SUPERUSER_EMAIL} already exists.')
EOF

exec "$@"
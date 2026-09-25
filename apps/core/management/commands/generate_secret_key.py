"""Print a new random value for RENTMASTER_SECRET_KEY:  python manage.py generate_secret_key"""
from django.core.management.base import BaseCommand
from django.core.management.utils import get_random_secret_key


class Command(BaseCommand):
    help = "Print a new random secret key."

    def handle(self, *args, **opts):
        self.stdout.write(get_random_secret_key())

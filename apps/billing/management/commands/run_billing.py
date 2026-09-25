"""Daily billing job. Schedule once a day (cron / Windows Task Scheduler):

    python manage.py run_billing

Every step is idempotent, so running it twice in a day is harmless.
"""
from datetime import date

from django.core.management.base import BaseCommand

from apps.billing import services


class Command(BaseCommand):
    help = "Generate invoices, apply late fees, poll pending mobile-money payments and send reminders."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=date.fromisoformat, default=None, help="Run as if today were YYYY-MM-DD")

    def handle(self, *args, **opts):
        result = services.run_daily(opts["date"] or date.today())
        for key, value in result.items():
            self.stdout.write(f"{key.replace('_', ' ').capitalize()}: {value}")
        self.stdout.write(self.style.SUCCESS("Billing run complete."))

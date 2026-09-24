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
        today = opts["date"] or date.today()
        created = services.generate_invoices(today)
        self.stdout.write(f"Invoices generated: {len(created)}")
        fees = services.apply_late_fees(today)
        self.stdout.write(f"Late fees applied: {len(fees)}")
        checked = services.poll_pending_payments()
        self.stdout.write(f"Pending mobile-money payments checked: {checked}")
        sent = services.send_reminders(today)
        self.stdout.write(f"Reminders sent: {sent}")
        self.stdout.write(self.style.SUCCESS("Billing run complete."))

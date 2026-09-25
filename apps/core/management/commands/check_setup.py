"""Go-live checklist:  python manage.py check_setup [--live]

Reports what is configured and, with --live, logs in to MTN MoMo and Airtel
Money to prove the credentials work. Nothing is charged. The same checks are
shown to Super Admins on the website at /system/setup/.
"""
from django.core.management.base import BaseCommand

from apps.core.setup_checks import FAIL, OK, WARN, run_checks


class Command(BaseCommand):
    help = "Check the production configuration (database, secrets, payments, SMS, email)."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true", help="Also test the MTN and Airtel credentials")

    def handle(self, *args, **opts):
        styles = {OK: self.style.SUCCESS, WARN: self.style.WARNING, FAIL: self.style.ERROR}
        results = run_checks(live=opts["live"])
        for status, label, detail in results:
            self.stdout.write(f"{styles[status](status.ljust(4))}  {label}" + (f": {detail}" if detail else ""))
        fails = sum(1 for r in results if r[0] == FAIL)
        self.stdout.write("")
        self.stdout.write(self.style.ERROR(f"{fails} problem(s) must be fixed before going live.") if fails
                          else self.style.SUCCESS("No blocking problems."))

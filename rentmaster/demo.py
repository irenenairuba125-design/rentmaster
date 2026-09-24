"""Demo mode for serverless hosting (Vercel) when no permanent database is configured.

Vercel only allows writing to /tmp, and each instance has its own /tmp. On a cold
start we copy the bundled demo database there, then bring invoices up to today.
Anything visitors change lasts only as long as that instance.

Rebuild the bundled database after model changes with:
    python manage.py build_demo_db
"""
import logging
import shutil
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("rentmaster")


def prepare():
    target = Path(settings.DATABASES["default"]["NAME"])
    if target.exists():
        return
    shutil.copyfile(settings.DEMO_DB_SOURCE, target)
    try:
        from django.core.management import call_command

        # No-op when the bundled copy is current; covers a stale copy after model changes.
        call_command("migrate", interactive=False, verbosity=0)
        from apps.billing import services

        services.generate_invoices()
        services.apply_late_fees()
    except Exception:  # the site must still come up with the bundled data
        logger.exception("Demo database catch-up failed")

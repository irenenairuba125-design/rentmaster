"""Rebuild the bundled demo database used in demo mode on Vercel:

    python manage.py build_demo_db

Run it after changing models, then commit demo/rentmaster-demo.sqlite3.
"""
import os
import subprocess
import sys

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create demo/rentmaster-demo.sqlite3 (migrated and seeded with demo data)."

    def handle(self, *args, **opts):
        target = settings.DEMO_DB_SOURCE
        target.parent.mkdir(exist_ok=True)
        target.unlink(missing_ok=True)
        env = {**os.environ, "RENTMASTER_SQLITE_PATH": str(target), "VERCEL": ""}
        # Separate processes so this project's normal database settings are untouched.
        for cmd in (["migrate", "--verbosity=0"], ["seed_demo"]):
            subprocess.run([sys.executable, "manage.py", *cmd], env=env, check=True, cwd=settings.BASE_DIR,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([sys.executable, "-c", (
            "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('DELETE FROM django_session'); "
            "c.commit(); c.execute('VACUUM'); c.close()"), str(target)], check=True)
        self.stdout.write(self.style.SUCCESS(f"Demo database written to {target} ({target.stat().st_size // 1024} KB)"))

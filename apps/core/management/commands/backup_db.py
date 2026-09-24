"""Database backup:  python manage.py backup_db [--keep 30]

Writes a compressed JSON dump of all data (works with SQLite and PostgreSQL)
to BACKUP_DIR and deletes the oldest backups beyond --keep. Schedule daily.
Private documents in PRIVATE_MEDIA_ROOT should be backed up alongside.
Restore with:  python manage.py loaddata <file>.json.gz
"""
import gzip
import io
from datetime import datetime

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Write a compressed backup of the database."

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=30, help="Number of backups to keep")

    def handle(self, *args, **opts):
        backup_dir = settings.BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        call_command("dumpdata", "--natural-foreign", "--natural-primary",
                     "--exclude=contenttypes", "--exclude=auth.permission", "--exclude=sessions", stdout=buf)
        path = backup_dir / f"rentmaster-{datetime.now():%Y%m%d-%H%M%S}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(buf.getvalue())
        old = sorted(backup_dir.glob("rentmaster-*.json.gz"))[:-opts["keep"]]
        for f in old:
            f.unlink()
        self.stdout.write(self.style.SUCCESS(f"Backup written: {path} ({path.stat().st_size // 1024} KB); removed {len(old)} old"))

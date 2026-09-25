"""Work done once when a server instance starts (see wsgi.py).

- Demo mode: copy the bundled demo database into place (rentmaster/demo.py).
- Real database on a host without a release step (Vercel): apply pending
  migrations, guarded by a PostgreSQL advisory lock so parallel cold starts
  don't race, then create the first admin account from environment variables.

Turn the automatic migration off with RENTMASTER_AUTO_MIGRATE=0 if you prefer
to run `python manage.py migrate` yourself.
"""
import logging
import os

from django.conf import settings

logger = logging.getLogger("rentmaster")
LOCK_ID = 7_314_202  # arbitrary, unique to this app


def pending_migrations():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    return executor.migration_plan(executor.loader.graph.leaf_nodes())


def migrate_if_needed():
    from django.core.management import call_command
    from django.db import connection

    if not pending_migrations():
        return False
    is_pg = connection.vendor == "postgresql"
    with connection.cursor() as cur:
        if is_pg:
            cur.execute("SELECT pg_advisory_lock(%s)", [LOCK_ID])
        try:
            if pending_migrations():  # another instance may have finished while we waited
                logger.info("Applying database migrations")
                call_command("migrate", interactive=False, verbosity=0)
        finally:
            if is_pg:
                cur.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
    return True


def ensure_admin():
    """Create the first Super Admin from RENTMASTER_ADMIN_USERNAME / _PASSWORD / _EMAIL.
    Never changes an existing account, so the variables can stay set safely."""
    username = os.environ.get("RENTMASTER_ADMIN_USERNAME", "").strip()
    password = os.environ.get("RENTMASTER_ADMIN_PASSWORD", "")
    if not (username and password):
        return None
    from apps.accounts.models import Role, User

    if User.objects.filter(username=username).exists():
        return None
    user = User.objects.create_superuser(username=username, password=password, role=Role.SUPER_ADMIN,
                                         email=os.environ.get("RENTMASTER_ADMIN_EMAIL", ""))
    logger.info("Created admin account %s", username)
    return user


def prepare():
    if settings.DEMO_MODE:
        from rentmaster import demo

        demo.prepare()
        return
    if not settings.ON_VERCEL or os.environ.get("RENTMASTER_AUTO_MIGRATE", "1") == "0":
        return
    try:
        migrate_if_needed()
        ensure_admin()
    except Exception:
        logger.exception("Startup database preparation failed")

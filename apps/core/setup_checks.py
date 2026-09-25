"""Go-live checks shared by `manage.py check_setup` and the admin Setup status page."""
from django.conf import settings

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def run_checks(live=False):
    """Return a list of (status, label, detail). With live=True also log in to
    MTN and Airtel to prove the credentials work (nothing is charged)."""
    from apps.billing.gateways import AirtelMoneyGateway, MtnMomoGateway

    out = []

    def add(status, label, detail=""):
        out.append((status, label, detail))

    def attempt(label, fn):
        try:
            fn()
            add(OK, label, "credentials accepted")
        except Exception as exc:
            add(FAIL, label, str(exc)[:200])

    # Security
    if settings.SECRET_KEY.startswith("django-insecure"):
        add(FAIL, "Secret key", "set RENTMASTER_SECRET_KEY to a long random value")
    else:
        add(OK, "Secret key", "set")
    add(WARN if settings.DEBUG else OK, "Debug mode", "ON - turn off in production" if settings.DEBUG else "off")

    # Database
    if settings.DEMO_MODE:
        add(WARN, "Database", "DEMO MODE - sample data that resets; connect a Postgres database (DATABASE_URL)")
    else:
        try:
            from django.db import connection

            from rentmaster.startup import pending_migrations

            connection.ensure_connection()
            pending = len(pending_migrations())
            add(OK, "Database", f"{connection.vendor} connected")
            add(WARN if pending else OK, "Database tables",
                f"{pending} update(s) pending - redeploy or run: python manage.py migrate" if pending else "up to date")
            if not pending:
                from apps.accounts.models import Role, User

                admins = User.objects.filter(role=Role.SUPER_ADMIN, is_active=True).count()
                add(OK if admins else FAIL, "Admin account",
                    f"{admins} super admin(s)" if admins else "none - set RENTMASTER_ADMIN_USERNAME and RENTMASTER_ADMIN_PASSWORD")
        except Exception as exc:
            add(FAIL, "Database", f"cannot connect: {exc}")

    # Payments
    mtn = settings.PAYMENT_PROVIDERS["MTN_MOMO"]
    if mtn["SUBSCRIPTION_KEY"] and mtn["API_USER"] and mtn["API_KEY"]:
        sandbox = mtn["TARGET_ENVIRONMENT"] == "sandbox"
        add(WARN if sandbox else OK, "MTN MoMo",
            f"configured ({mtn['TARGET_ENVIRONMENT']}, {mtn['CURRENCY']})" + (" - TEST mode, no real money" if sandbox else " - LIVE"))
        if live:
            attempt("MTN MoMo login", lambda: MtnMomoGateway()._token())
    else:
        add(WARN, "MTN MoMo", "not configured - tenants' MTN payments wait for manual confirmation"
            + (" (demo site simulates them)" if settings.DEMO_MODE else ""))

    airtel = settings.PAYMENT_PROVIDERS["AIRTEL_MONEY"]
    if airtel["CLIENT_ID"] and airtel["CLIENT_SECRET"]:
        test = "openapiuat" in airtel["BASE_URL"]
        add(WARN if test else OK, "Airtel Money", "configured" + (" - TEST (UAT) mode, no real money" if test else " - LIVE"))
        if live:
            attempt("Airtel Money login", lambda: AirtelMoneyGateway()._headers())
    else:
        add(WARN, "Airtel Money", "not configured - tenants' Airtel payments wait for manual confirmation"
            + (" (demo site simulates them)" if settings.DEMO_MODE else ""))

    site = settings.RENTMASTER["SITE_URL"]
    add(OK if site.startswith("https://") else WARN, "Site address (payment callbacks, receipt QR codes)", site)

    # Messaging and files
    add(OK if settings.SMS["USERNAME"] and settings.SMS["API_KEY"] else WARN, "SMS (Africa's Talking)",
        "configured" if settings.SMS["API_KEY"] else "not configured - SMS are only written to the log")
    console = "console" in settings.EMAIL_BACKEND or "locmem" in settings.EMAIL_BACKEND
    add(WARN if console else OK, "Email", "not configured - emails are only written to the log" if console else "configured")
    add(OK if settings.CRON_SECRET else WARN, "Daily billing job (invoices, late fees, reminders)",
        "scheduled daily at 07:00 Kampala time" if settings.CRON_SECRET else "off - set CRON_SECRET to switch it on")
    if settings.ON_VERCEL:
        add(WARN, "Uploaded files", "stored temporarily on Vercel - photos and documents can disappear; add object storage before relying on uploads")
    return out

# RENTMASTER — Smart Property & Rental Management

A Django + Django REST Framework system for managing rental properties in Uganda.
The core flow is **Owner → Property → Building → Unit → Tenant → Lease → Invoice → Payment → Receipt**.
Mobile money (MTN and Airtel) is a first-class payment method.

## Quick start (Windows)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo      # optional demo data
.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000. Every demo login uses the password `Rentmaster@2026`:

| Username     | Role                      |
|--------------|---------------------------|
| `admin`      | Super Admin (also /admin) |
| `owner`      | Property Owner / Landlord |
| `manager`    | Property Manager          |
| `accountant` | Accountant                |
| `caretaker`  | Caretaker                 |
| `john`       | Maintenance Staff         |
| `ronald`     | Tenant (unit A102)        |

To start with an empty database instead, run `python manage.py createsuperuser`. Then create the other users in `/admin`.

## Modules

| Module | Where |
|---|---|
| Users & roles (RBAC) | `apps/accounts` for roles. `apps/core/scoping.py` sets which rows each role can see. |
| Properties, buildings, units | `apps/properties` |
| Tenants (TEN-000001), documents, portal logins | `apps/tenants` |
| Leases: expiry alerts, move-out, security deposits | `apps/tenants`, `apps/billing` (`DepositTransaction`) |
| Invoices (INV-2026-00001): recurring rent, utilities, late fees | `apps/billing/services.py` |
| Payments: MTN MoMo, Airtel Money, bank, card, cash | `apps/billing/gateways.py`, `services.py` |
| Receipts (REC-2026-00001) with a QR verification page | `billing/receipts/…`, `/billing/receipts/verify/<code>/` |
| Arrears: Paid → Partially paid → Due → Overdue → Serious arrears | `/billing/arrears/` (CSV export) |
| Utility meter readings, billed onto the next invoice | `/billing/utilities/` |
| Maintenance tickets (MT-00001): assign, status flow, comments, costs | `apps/maintenance` |
| Expenses and financial reports (income, expenses, net, occupancy) | `apps/finance` |
| Notifications: in-app, email, SMS (Africa's Talking) | `apps/core/notify.py` |
| Audit trail: every create, update and delete, plus logins and payment actions | `apps/core/audit.py`, `/audit/` |
| Inspections (INS-0001): move-in, move-out and routine checklists with photos; a damaged item can open a maintenance ticket | `apps/inspections` |
| Vacancies: public listings at `/vacancies/`, online applications (APP-00001), viewings by SMS, approval that creates the tenant | `apps/vacancies` |
| Documents: IDs, agreements and expense receipts stored privately and served only to people allowed to see them | `apps/core/documents.py`, `private_media/` |
| Announcements to every tenant of a property (in-app, email, optional SMS) | `/announcements/new/` |
| Two-factor login (authenticator app), also used for `/admin` | `apps/accounts/totp.py`, `views.py` |
| REST API for a future Flutter app | `/api/` and `/api/me/` (a tenant's balance) |

## How payments are verified

A payment is **never** marked paid just because someone typed in a transaction reference.

* **MTN MoMo / Airtel Money:** RENTMASTER sends a payment prompt to the payer's phone. The payment then stays `PENDING` until the provider's status API says `SUCCESSFUL` *for the expected amount*. Provider callbacks don't count as proof. They only make the system ask the provider for the payment's status again.
* **Bank transfer submitted by a tenant:** stays `PENDING` until an accountant finds the transaction on the bank statement. The accountant then enters the statement reference and confirms.
* **Cash, or money finance staff have already confirmed:** recorded by finance staff (Accountant, Manager or Super Admin), who must tick a confirmation box.

Every verification is written to the audit trail. It issues a receipt, updates the invoice and notifies the tenant and the landlord.

To turn on live mobile-money collection, set these environment variables:

```
MTN_MOMO_SUBSCRIPTION_KEY, MTN_MOMO_API_USER, MTN_MOMO_API_KEY,
MTN_MOMO_BASE_URL, MTN_MOMO_TARGET_ENV
AIRTEL_CLIENT_ID, AIRTEL_CLIENT_SECRET, AIRTEL_BASE_URL
RENTMASTER_SITE_URL=https://your-domain   # public HTTPS URL, needed for provider callbacks
```

Until these are set, mobile-money requests are saved as pending so the accounts office can confirm them by hand.

## Mobile app API

The API is what the Flutter app will use. Every endpoint only returns records the signed-in user is allowed to see.

| Call | What it does |
|---|---|
| `POST /api/auth/login/` with `{"username", "password", "code"?, "device"?}` | Returns a `token` that is valid for 30 days. If the user has two-factor login on, the reply is `401` with `"two_factor_required": true`; send the request again with the 6-digit `code`. After 5 failed attempts the account is locked out for 15 minutes. |
| `POST /api/auth/logout/` | Revokes the token. Admins can also revoke a lost phone's token in `/admin`. |
| `GET /api/me/` | The signed-in user. For tenants it also includes their unit, balance and open invoices. |
| `GET /api/properties/ units/ leases/ invoices/ payments/ maintenance/` | Lists. Append an id for a single record. |
| `POST /api/maintenance/` | Report an issue. |
| `POST /api/invoices/<id>/pay/` with `{"method": "MTN_MOMO" or "AIRTEL_MONEY", "amount", "phone"}` | Tenant only. Sends a mobile-money payment prompt to the phone. The payment starts as `PENDING`. |
| `POST /api/payments/<id>/check/` | Asks the provider for the payment's status. The payment becomes `VERIFIED`, with a receipt number, only when the provider confirms it. |

Send the token on every request as `Authorization: Bearer <token>`. Only a hash of each token is stored in the database. Plain username-and-password (HTTP Basic) authentication is switched off, so a password alone can never get past two-factor login.

## Daily job

```
python manage.py run_billing          # add --date YYYY-MM-DD to backfill
```

Schedule this command once a day with Windows Task Scheduler or cron. Each run:

* generates invoices for the current period
* applies late fees once the grace period has passed
* checks pending mobile-money payments with the provider
* sends rent due, overdue and lease-expiry reminders (at 30, 14 and 7 days)
* marks ended leases as expired

It is safe to run more than once.

Also schedule a daily backup:

```
python manage.py backup_db --keep 30
```

This writes a compressed dump to `backups/` (or `RENTMASTER_BACKUP_DIR`) and keeps the latest 30. Restore one with `python manage.py loaddata <file>.json.gz`. Copy `private_media/` along with it, because that folder holds the uploaded documents.

## Production settings

Set these environment variables:

* `RENTMASTER_DEBUG=false`
* `RENTMASTER_SECRET_KEY`
* `RENTMASTER_ALLOWED_HOSTS`
* `RENTMASTER_DB_ENGINE=postgresql` plus the `RENTMASTER_DB_*` variables (install `psycopg`)
* an SMTP `RENTMASTER_EMAIL_BACKEND`
* `AFRICASTALKING_USERNAME` and `AFRICASTALKING_API_KEY` for SMS
* `RENTMASTER_REQUIRE_2FA_ROLES=SUPER_ADMIN,ACCOUNTANT,OWNER` to make those roles set up two-factor login

Once `DEBUG` is off, HTTPS redirects, secure cookies and HSTS turn on. Your web server must **not** serve `private_media/`. Only `media/` (property, unit and maintenance photos) is public.

## Tests

```
python manage.py test apps
```

The tests cover:

* payment verification: forged references, callbacks and amount mismatches
* role and row-level access control
* invoice periods, late fees, utilities and arrears classes
* a smoke test that renders every page for every role
* inspections, vacancy applications (including spam protection and approval), two-factor login and document permissions

## Not built yet (next steps)

* WhatsApp notifications (the WhatsApp Business API needs a Meta business account and approved message templates)
* server-side PDF generation (receipts and invoices use the browser's print-to-PDF)
* AI assistant
* the Flutter app itself (its API, including login and rent payment, is ready)

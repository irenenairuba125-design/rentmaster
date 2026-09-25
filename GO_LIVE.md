# Going live with RENTMASTER on Vercel

This guide takes the demo site at https://rentmaster-chi.vercel.app to a real system that stores data permanently and collects rent through MTN Mobile Money and Airtel Money.

You don't need a terminal for steps 1–3. When you finish a step, sign in as your admin and open **Setup status** in the menu to check it worked.

Everywhere below, **"add a variable"** means: in your Vercel project, open **Settings → Environment Variables**, add the name and value, and tick **Production**. Settings only take effect after a redeploy, so finish with **Deployments → ⋯ → Redeploy** on the latest deployment.

---

## 1. Secret key and your admin account (5 minutes)

Add these variables:

| Name | Value |
|---|---|
| `RENTMASTER_SECRET_KEY` | A long random value, at least 50 characters, and never shared. You can get one from `python manage.py generate_secret_key`, or type 50+ random letters, digits and symbols. |
| `RENTMASTER_ADMIN_USERNAME` | The username you want for yourself, for example `nalwoga.admin`. |
| `RENTMASTER_ADMIN_PASSWORD` | A strong password of at least 12 characters. |
| `RENTMASTER_ADMIN_EMAIL` | Your email address. |
| `RENTMASTER_COMPANY_NAME` | Your business name. It appears on invoices and receipts. |
| `CRON_SECRET` | Another long random value, different from the secret key. It switches on the daily billing job (see section 7). |

The admin account is created the first time the site starts with a real database (step 2). It is never overwritten afterwards, so you can leave the variables in place.

## 2. Permanent database (10 minutes, free tier available)

1. In your Vercel project, open **Storage → Create Database → Neon (Serverless Postgres)** and follow the prompts. Choose the region closest to your users (Europe is closest to Uganda).
2. Connect the database to this project. Vercel adds `DATABASE_URL` for you.
3. **Redeploy.**

On the first start with the database, RENTMASTER:

* creates all its tables
* creates your admin account from step 1
* turns off demo mode: the yellow "Demo site" banner and the simulated payments disappear

The new database is **empty**. Sign in with your admin account and add your properties, units, tenants and leases. Then create logins for staff under **Users & admin**, and for tenants with **Create portal login** on each tenant's page.

> Want the sample data in the real database to practise on first? Run `python manage.py seed_demo` once from a computer, with `DATABASE_URL` set to the same value that Vercel shows. Only do this on a practice database.

## 3. SMS and email (optional, 15 minutes)

**SMS** (rent reminders, payment confirmations): open an account at https://africastalking.com, then add:

| Name | Value |
|---|---|
| `AFRICASTALKING_USERNAME` | Your app username |
| `AFRICASTALKING_API_KEY` | Your API key |
| `AFRICASTALKING_SENDER_ID` | Optional. Your approved sender name. |

**Email:** use any SMTP provider, such as Gmail with an app password, Zoho or Brevo:

| Name | Value |
|---|---|
| `RENTMASTER_EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | From your provider |
| `RENTMASTER_FROM_EMAIL` | For example `Royal Apartments <rent@yourdomain.com>` |

## 4. MTN Mobile Money

### 4a. Test first (sandbox, same day, free)

1. Sign up at https://momodeveloper.mtn.com, subscribe to the **Collections** product, and copy its **Primary Key**.
2. On a computer with this project, run:
   ```
   python manage.py mtn_sandbox_user --subscription-key YOUR_PRIMARY_KEY --host rentmaster-chi.vercel.app
   ```
   It prints six variables (`MTN_MOMO_...`). Add them all in Vercel and redeploy.
3. In **Setup status**, click **Test payment logins**. MTN should show **credentials accepted**.
4. Sign in as a tenant and pay. MTN's sandbox approves the payment without real money, and the receipt appears on its own.

### 4b. Real money (production)

MTN Uganda must approve your business first (their "Go Live" / KYC process). You'll usually need:

* business registration (URSB) documents and a TIN
* the directors' IDs
* a bank account for settlements

After approval MTN gives you production credentials. Add or replace these variables:

| Name | Value |
|---|---|
| `MTN_MOMO_BASE_URL` | `https://proxy.momoapi.mtn.com` |
| `MTN_MOMO_TARGET_ENV` | `mtnuganda` |
| `MTN_MOMO_CURRENCY` | `UGX` |
| `MTN_MOMO_SUBSCRIPTION_KEY` | Production Collections key from the MTN partner portal |
| `MTN_MOMO_API_USER` / `MTN_MOMO_API_KEY` | Production API user and key |
| `RENTMASTER_SITE_URL` | `https://rentmaster-chi.vercel.app`, or your own domain |

Check the exact values against what MTN sends you, because they sometimes differ by country and account.

## 5. Airtel Money

Register at https://developers.airtel.africa and create an application with the **Collection** product.

* **Testing (UAT):** add `AIRTEL_CLIENT_ID` and `AIRTEL_CLIENT_SECRET` from the UAT app. The default base URL is already the test one.
* **Real money:** after Airtel Uganda approves your business (similar documents to MTN), add the production client ID and secret, and set `AIRTEL_BASE_URL` to `https://openapi.airtel.africa`.

## 6. Make two-factor login compulsory for staff who handle money

Add `RENTMASTER_REQUIRE_2FA_ROLES` = `SUPER_ADMIN,ACCOUNTANT,OWNER`. Those users are asked to set up an authenticator app the next time they sign in.

## 7. Known limits on Vercel

* **Uploaded files** (tenant IDs, photos, signed agreements) are stored only temporarily on Vercel and can disappear. Until object storage is added, keep the originals yourself.
* **The daily billing job** (monthly invoices, late fees, payment checks and reminders) runs every day at 07:00 Kampala time through Vercel Cron. It only runs once you add a `CRON_SECRET` variable, which can be any long random value. Vercel sends it with each scheduled call. Accountants can also press **Generate invoices** on the Invoices page at any time.

---

**How payments stay safe:** a payment is marked paid only when MTN or Airtel confirms it for the right amount, or when an accountant confirms money they can see on a statement. A tenant typing in a reference number is never enough.

# YAAN — Employee Transport Management Platform

React + TypeScript (Vite) · FastAPI · PostgreSQL. Spec: `YAAN_Product_Spec_Final.md`.

Roles: Super Admin · Vendor Admin · Operator · Driver. Vendor isolation is enforced by the API on every request.

## Run locally (Windows)

Prerequisites: Node.js 24, Python 3.12, PostgreSQL (a `yaan` database and role — see "Database").

```
# backend  (http://localhost:8000, API docs at /docs in development)
cd backend
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.seed          # super admin + 2 vendors
.\.venv\Scripts\python -m app.seed_demo     # optional: realistic demo data for every module
.\.venv\Scripts\uvicorn app.main:app --reload

# frontend (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Demo logins (**development only**, password `DevOnly#2026`): `superadmin`, `admin_alpha`, `ops_alpha1`, `drv_alpha1`
(and the `bravo` equivalents). `seed_demo` sends nothing for real — SMS/email go to the console.

## Tests
```
cd backend;  .\.venv\Scripts\pytest          # API, business rules, security, concurrency (uses the yaan_test database)
cd frontend; npm test                         # UI: navigation, guards, login, forms, charts
```

## Database
PostgreSQL 15+ with the `btree_gist` extension (used by the constraints that make double-booking a driver/vehicle
impossible even under concurrent requests). Migrations: `alembic upgrade head` (creates the extension; on managed
Postgres enable it once as an admin).

## Configuration (`backend/.env`, never committed)
| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development` or `production`. Production refuses to start with a default/short `JWT_SECRET`, hides `/docs`, adds HSTS |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/yaan` |
| `JWT_SECRET` | random, 32+ characters |
| `FRONTEND_URL`, `CORS_ORIGINS` | where the React app is served (links in emails, CORS) |
| `AWS_SES_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EMAIL_FROM` | AWS SES (used first when `AWS_SES_REGION` is set). `EMAIL_FROM` must be a verified SES identity; in the SES sandbox recipients must be verified too. Optional `AWS_SES_CONFIGURATION_SET` |
| `SENDGRID_API_KEY`, `EMAIL_FROM` | all email: onboarding / password reset and trip notifications (with the OTP). Unset (and no SMTP) = emails are printed to the console |
| `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_SSL` | SMTP email, used whenever `SMTP_HOST` is set (before SendGrid). **Zoho Mail:** `smtp.zoho.in` (India) / `smtp.zoho.com` (global), port `465` + `SMTP_USE_SSL=true` (or `587` + `false`), username = full mailbox address, password = a Zoho app-specific password. `EMAIL_FROM` must be that mailbox or one of its aliases |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | trip SMS. Unset = SMS are printed to the console |
| `PUBLIC_BASE_URL` | public URL of the API; enables Twilio delivery-status callbacks (`/api/webhooks/twilio/status`) |
| `DEFAULT_COUNTRY_CODE` | applied to phone numbers stored without one (default `+91`) |
| `BUSINESS_TIMEZONE` | day boundaries, filters, message times (default `Asia/Kolkata`) |
| `AVAILABILITY_BUFFER_MINUTES` | gap required between trips of one driver/vehicle (confirmed rule: 30) |
| `ON_TIME_GRACE_MINUTES`, `ACCEPTANCE_WARNING_MINUTES` | dashboard thresholds |
| `OTP_LENGTH`, `OTP_MAX_ATTEMPTS` | drop-off OTP digits (default 4) and wrong tries before an employee's OTP locks (default 5) |

## Key business rules (all enforced server-side)
* Onboarding: the Super Admin creates any user; a **Vendor Admin creates Operators and Drivers of their own vendor** (never other Vendor Admins, never another vendor). Temp password generated, shown once, hashed, valid 5 days; the email carries a one-time set-password link, never the password.
* **Trip workflow:** an **Operator requests** a trip (customer, site, time, employees, addresses — no driver/vehicle) → status *Awaiting assignment*, nothing reserved, nobody notified → a **Vendor Admin assigns** an available driver and vehicle (all availability/capacity rules apply) → the trip becomes *Assigned* and **only then** the driver and employees get their SMS. A Vendor Admin/Super Admin can also create-and-assign in one step. A request can be rejected with a reason (no SMS). Operators may edit/cancel a request only while it is awaiting assignment; afterwards only a Vendor Admin can.
* **Drop-off OTP:** when a trip becomes *Assigned*, each employee gets a 4-digit OTP, sent by SMS and/or Email. At their drop point the employee tells it to the driver, who enters it per employee; **the driver can end the trip only when every employee is either OTP-verified or marked "not dropped" with a reason** (the latter is flagged on the trip and the dashboard). 5 wrong tries lock that employee's OTP (the driver then marks them not dropped). The OTP is shown only to the Operator who requested the trip, beside each employee; it is derived from a per-row secret, never stored, logged, audited, or shown in the notification logs (masked as ••••). The driver never receives it.
* **Notification channels (Settings, Super Admin and Vendor Admin, per vendor):** SMS (default on) and Email (default off) switch independently; both on = both are used, one on = only that one, both off = nothing is sent (the UI warns that employees will not receive their OTP). Drivers may have an optional email, otherwise their login email is used.
* **Mandatory fields:** Employee: site, shift, email, address, latitude, longitude. Customer: contact person, email, address, latitude, longitude. Vendor: primary contact, email, address.
* **Operators belong to one customer** (set when the Vendor Admin/Super Admin creates them; changeable later). An Operator's employee and trip forms don't ask for a customer: the heading says e.g. "Add employee for Acme", the server forces that customer whatever is sent, and they see only that customer's employees and trips. Vendor Admins and Drivers stay vendor-level. An Operator not yet tagged is told to ask their admin.
* Operators can add and edit employees of their own vendor (not deactivate them).
* A trip blocks its driver and vehicle until 30 minutes after it ends. Capacity ≥ passengers + 1 escort seat if any passenger is female.
* Trips are never hard-deleted. Cancelling releases the driver/vehicle. Started trips only allow instruction edits.
* Trip SMS is queued inside the trip transaction and sent afterwards — a provider outage never blocks a trip; failed messages can be retried.
* Deactivating a vendor locks out all its users immediately.
* Compliance = hand-entered document types and expiry dates (no file uploads); "about to expire" window is configurable (default 30 days).
* Expenses: every role can record one (category, amount in INR, payment method, optional vehicle/driver); the entrant's name is stored. Drivers and Operators see only their own, Vendor Admins their vendor's, Super Admin all. The entrant may edit/void for 24 h (EXPENSE_EDIT_WINDOW_HOURS), admins any time; nothing is deleted, voided entries are excluded from totals. Summaries: Super Admin (all vendors) and Vendor Admin (own vendor) only; Excel export under Reports.

## Docs
* `docs/SMS_TEMPLATES.md` — exact SMS wording in DLT-registration format, plus India delivery notes.

## Before going to production — checklist
1. Set `ENVIRONMENT=production`, a random `JWT_SECRET`, real `DATABASE_URL` (non-superuser role), HTTPS in front of the API and the app.
2. Rotate any credential that was ever pasted into chat or committed; set real SendGrid/Twilio values.
3. India SMS: DLT-registered sender + templates (see `docs/SMS_TEMPLATES.md`); Twilio trial accounts and US numbers will not deliver there.
4. Never run `app.seed` / `app.seed_demo` against production (they refuse unless `ENVIRONMENT=development`).
5. Login throttling is in-memory (single instance). Behind several instances, move it to Redis.
6. Back up PostgreSQL; the audit trail (`audit_logs`) and trip history are append-only by design.

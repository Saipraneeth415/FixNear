# FixNear: Local Service Booking Platform

FixNear lets customers find local service providers and book repair or cleaning
services (plumbing, electrical, AC, laptop, bike and home cleaning). It is a
full-stack **portfolio project** built step by step with Flask.

> **Sample data only.** Every service, price and provider in this project is
> labelled sample data. FixNear does not list real businesses, take real
> bookings or process payments.

> **Verification status.** You reported the full test suite (399 tests, Stages 1 to 6)
> passing on your machine. **Stage 7 has NOT been verified**: it was written where
> SQLAlchemy, Flask-Login and Flask-WTF could not be installed, so only the pure-Python
> rules (admin rules, booking rules and others, 91 tests) and template rendering were
> actually run. Everything that touches the database, forms or login sessions is
> untested until you run the commands below and the full suite passes.

## Status

| Stage | Feature | Status |
|---|---|---|
| 1 | Homepage, search, filters, service pages, error pages | Done |
| 3 | SQLite database, seeding command | Done |
| 4 | Registration, login, logout, roles, CSRF, admin command | Done (you reported it passing) |
| 5 | Customer booking workflow | Done (you reported it passing) |
| 6 | Provider dashboard, accept/reject, progress, assignment, conflict checks | Done (you reported it passing) |
| 7 | Admin dashboard: live numbers, user management, service and category management, all bookings | **Written, unverified** |
| 8 | pytest suite, security and accessibility review | Not started |
| 9 | Deployment | Not started |
| 10 | Screenshots, final README, resume description | Not started |

## What Stage 7 added

No database change was needed: everything uses columns that already exist, so there is **no migration**.

| URL | Purpose |
|---|---|
| `/admin/dashboard` | Live counts: users, customers, providers, services, bookings, pending, completed (plus a few more) and the 5 newest bookings |
| `/admin/users` | All accounts with role and status; search, filters, pages; activate or deactivate |
| `/admin/services` | Every category and service (including hidden ones) with booking counts |
| `/admin/services/new`, `/admin/services/<slug>/edit` | Create and edit a service |
| `/admin/services/<slug>/hide` or `/show` (POST) | Hide a service from the site, or show it again |
| `/admin/services/<slug>/delete` | Confirm page (GET); deletes only if safe (POST) |
| `/admin/categories/new`, `/<slug>/edit`, `/<slug>/delete` | The same for categories |
| `/admin/bookings` | Every booking: reference, customer, provider, service, appointment, status; filters and pages. Read-only |

### Who can use it

- **Only an active administrator.** Every route is checked on the server. Visitors are sent to login; customers and providers get "Access denied"; a deactivated admin is logged out on their next request.
- Every change is a **POST with a CSRF token**. Opening a change address in the browser (GET) does nothing.
- The functions that change data check for an active admin again themselves, so the rule holds even if a page is ever reused.

### Safety rules (enforced on the server)

- **Users:** you cannot deactivate your own account, and the last active administrator can never be deactivated. Roles and passwords cannot be changed here. Deactivating someone logs them out at once and stops them logging in; nothing is deleted. Deactivating a provider keeps their bookings and links, tells you how many active bookings remain assigned, and new bookings skip them.
- **Services:** a service that has bookings can never be deleted (booking history stays intact). Hide it instead: it disappears from the site and takes no new bookings, and existing bookings are untouched. Deleting an unused service also removes its provider links, so no provider is left offering something that no longer exists. A service's address (slug) cannot change after creation, and old bookings keep the price they were made at.
- **Categories:** a category that still has services (hidden ones count) cannot be deleted.
- **Inputs:** addresses must be lower-case letters, digits and single hyphens and must be unique; prices must be whole numbers from 0 to 1,000,000; text lengths and the "included" list are limited; icons come from a fixed list. Text is escaped wherever it is shown.
- **Searches** treat `%` and `_` as ordinary characters, and unknown filters or page numbers are ignored, never errors.

### What the admin area does NOT do yet

- It does not change booking statuses or reassign providers (the bookings page is read-only).
- It does not create provider accounts or link providers to services. Use `create-provider` and `provider-services` on the command line.
- It cannot change a user's role.
- Provider name and area on a service are still plain text shown on the page.

## What Stage 6 added

| URL | Who | Purpose |
|---|---|---|
| `/provider/dashboard` | providers | Totals, requests waiting for a response, upcoming and active jobs, recently completed |
| `/provider/bookings` | providers | All their jobs, soonest first, with a `?status=` filter |
| `/provider/bookings/<reference>` | the assigned provider | Full job details, progress, and the buttons that fit the status |
| `POST /provider/bookings/<reference>/<action>` | the assigned provider | `accept`, `reject`, `start` or `complete` (CSRF-protected, POST only) |

### How a booking gets a provider (assignment)

The database already had an empty `provider_id` on every booking, but nothing said
**which provider offers which service**. So Stage 6 adds one small table,
`provider_services`, and that is the only schema change.

When a customer books, **the server** (never the customer) chooses the provider:

1. Providers who offer that service, are active, and are **free** at that time are candidates.
2. The one with the fewest active jobs that day gets it (lowest account number breaks a tie).
3. If providers offer the service but **all are busy**, the customer is told: "No provider is available for that date and time. Please choose another time." Nothing is saved.
4. If **no provider offers the service at all** (the case for all sample data until you link one), the booking is saved unassigned and Pending, exactly as in Stage 5.

`flask assign-pending` gives providers to Pending bookings that were made before
any provider offered the service.

### What a provider can do

```text
Pending  --accept-->  Accepted  --start job-->  In Progress  --mark completed-->  Completed
Pending  --reject-->  Rejected
```

- Providers use the **same status rules** as everything else (`services/booking_rules.py`). Pending cannot jump to Completed; final statuses cannot be changed.
- The server checks the booking's **current** status on every click, so a stale page cannot force a change (for example accepting a booking the customer has just cancelled).
- Repeating an action (a double click) changes nothing and says so.
- Providers cannot cancel. Customers still cancel under the Stage 5 rules.

### Availability and conflict rules

- A job reserves **2 hours from its start time**. A provider cannot be given, or accept, two active jobs whose start times are less than 2 hours apart on the same day (`JOB_BLOCK_MINUTES` in `services/booking_rules.py`).
- When **assigning**, every active booking (pending, accepted, in progress) blocks the time.
- When **accepting**, only jobs the provider has already committed to (accepted, in progress) block it.
- Rejected, cancelled and completed bookings free the time.

### Who can see what

- A provider only ever sees bookings **assigned to them**. Someone else's booking, an unassigned booking and a made-up reference all give the same "Page not found". Customers and admins get "Access denied" on provider pages.
- The assigned provider sees the customer's name, phone, address and problem description (needed for the job), **never the customer's email**.
- Customers see the provider's **name** only, never their email.

### Honest limits of Stage 6

- **No working hours or days off.** Availability means "not already booked". Working-hours windows need their own table and are left for later.
- **The 2-hour block is a simple rule**, not each service's real duration.
- **Conflict checks are not locked against two simultaneous requests** by the same provider. With SQLite and one provider clicking at a time this is very unlikely, but it is not a database-level guarantee.
- **Rejecting is final** and gives no reason. The customer must book again.
- **No reassignment or admin tools yet.** Provider accounts and service links are managed from the command line until the Stage 7 admin dashboard.
- Providers and services are linked by hand. There is no provider approval or profile page yet.
- No emails or SMS notifications.

## What Stage 5 added

A customer can: open a service, click **Book this service**, log in or register
(and come straight back), fill in the booking form, get a unique reference,
see their bookings on the dashboard and in **My bookings**, open a booking to
see its status, and cancel it when the rules allow.

| URL | Who | Purpose |
|---|---|---|
| `/services/<slug>/book` | customers | Booking form for that service (the service is fixed by the URL) |
| `/bookings/<reference>/confirmation` | the owner | "Your booking is saved" page |
| `/bookings` | customers | History, with `?status=` filter |
| `/bookings/<reference>` | the owner | Details and progress |
| `/bookings/<reference>/cancel` | the owner | Confirm and cancel (GET shows the page, POST cancels) |
| `/customer/dashboard` | customers | Real totals and the 5 most recent bookings |

### Booking statuses and allowed changes

```text
Pending --> Accepted --> In Progress --> Completed
   |           |
   |           +--> Cancelled
   +--> Rejected
   +--> Cancelled
```

Anything not on this diagram is refused by the server (for example Pending
straight to Completed, or reopening a Completed booking). Completed, Rejected
and Cancelled are final. The rules live in `services/booking_rules.py`.

In Stage 5 only the customer's **Cancel** is wired up. Accept, reject, start and
complete are used by providers in Stage 6 through `transition_status()`.

### Cancellation rules

- **Pending:** the customer can cancel at any time.
- **Accepted:** the customer can cancel until 24 hours before the appointment.
- **In Progress, Completed, Rejected, Cancelled:** cannot be cancelled.

### Booking rules enforced on the server

- Only logged-in **customer** accounts can book. Providers and admins get "Access denied".
- The service must exist and be **available**. Unavailable services are hidden from the site and cannot be booked.
- The date cannot be in the past (and must be within 90 days). The time must be one of the offered slots (8:00 AM to 7:30 PM, every 30 minutes). Today's earlier times are refused.
- Name 2 to 100 characters, address 10 to 300, problem description 10 to 1000, phone with 10 to 15 digits.
- Status, provider, price, customer and reference are **never read from the request**. A new booking is always Pending, has no provider, takes its starting price from the service, and belongs to the logged-in user.
- A customer can only open or cancel **their own** bookings. Someone else's booking looks exactly like a booking that does not exist (a 404).
- A double click or page refresh cannot create two bookings: each form carries a one-time token. The same customer also cannot hold two active bookings for the same service and time.

### Booking reference

Looks like `FN-7K4M-9QXT`. It is random (not a counter), uses letters and digits
that are hard to confuse (no 0, O, 1, I or L), is unique in the database, and
never changes after creation. It is not the internal ID, and the ID does not work
in URLs. If a generated reference is already taken, a new one is generated (up
to 5 tries).

### What Stage 5 does NOT do (honest limits)

- **No provider assignment and no time-slot conflict checking.** The `bookings`
  table has an empty, optional `provider_id`. Stage 6 will fill it in when a
  provider accepts, and will add the availability and conflict checks. Until then
  all bookings stay Pending unless changed in the database. The only duplicate
  protection is per customer.
- No emails or SMS, no payments, no reviews yet (reviews need Completed bookings).
- No pagination on the history page.
- Appointment times use a fixed offset from UTC (`BOOKING_UTC_OFFSET_MINUTES`,
  default 330 = India). It does not handle daylight saving.

## What Stage 4 added

- **Pages:** `/register`, `/login`, `/logout` (POST only), `/dashboard` (sends you to your own dashboard).
- **Dashboards:** `/customer/dashboard`, `/provider/dashboard`, `/admin/dashboard`. They are **placeholders**: no booking, provider or admin tools exist yet and the pages say so.
- **`users` table:** unique lower-case email, hashed password, role (`customer`, `provider`, `admin`), active flag, last login time, timestamps.
- **First administrator:** created from the command line with a password you type. No password is stored in code.
- Your services, categories and search are unchanged. Existing data is never touched.

## Security decisions (in plain English)

| Decision | Why |
|---|---|
| Passwords are hashed with Werkzeug (scrypt, salted) | If the database leaks, attackers get slow-to-crack hashes, not passwords. The same password gives different hashes for different users. |
| Password rules: 10 to 128 characters, a letter and a number, not a common password, not your email or name | Length matters most. The maximum stops huge inputs from slowing the server. |
| Public registration always creates a **customer** | The route sets the role in code. The form has no role field, and extra values like `role=admin` are ignored. |
| Roles are checked on the server for every protected route | Hiding a button is not security. Not logged in goes to login; the wrong role gets a 403 page. |
| CSRF tokens on every form (Flask-WTF) | Another website cannot make your browser submit a form to FixNear. |
| Logout is a POST with a token | A malicious link or image cannot log you out. |
| `next` redirects only accept paths on this site | Stops `/login?next=https://evil.example` open-redirect tricks. |
| One message, "Invalid email or password." | Does not reveal which emails have accounts. Unknown emails still spend the same hashing time. |
| Suspended or deleted users are logged out on their next request | The user is reloaded from the database on every request, so role changes also apply immediately. |
| Session cookie is HttpOnly and SameSite=Lax; Secure in production | Scripts cannot read it; it is not sent on cross-site posts; it only travels over HTTPS when deployed. |
| Private pages send `Cache-Control: no-store` | The browser's Back button will not show a private page after logout. |
| Error pages never show stack traces | Details go to the server log only. |

### Known limitations (planned for later stages)

- No limit on repeated wrong passwords (rate limiting comes in Stage 8).
- No email verification, no password reset and no "remember me".
- The registration form says when an email already exists (the requirement was to reject duplicates). That lets someone test whether an email is registered; rate limiting is the usual fix.
- Provider accounts cannot be created yet. Admin tools to create and approve providers arrive in Stages 6 and 7.

## Install and run on Windows (PowerShell in VS Code)

Run these from the `FixNear` folder in the VS Code terminal. No new packages were
added in Stage 6, but run the install step anyway.

### 1. Install the packages

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Update the database (nothing new for Stage 7; this section is from Stage 6)

Your earlier migrations already exist, so do **not** run `db init` again and do not
delete anything. Make sure you are up to date, then generate the new migration:

```powershell
flask --app app db upgrade
flask --app app db migrate -m "Add provider services table"
```

**Inspect the new file before applying it:**

```powershell
Get-ChildItem migrations\versions\*.py | Sort-Object LastWriteTime | Select-Object -Last 1 | Get-Content
```

It should contain only `op.create_table('provider_services', ...)` with:

- `provider_id` and `service_id` columns, together forming the primary key;
- foreign keys to `users` and `services`, both with `ondelete='CASCADE'`;
- a `created_at` column;
- an index on `service_id`.

**Stop and send me the file if you see any `drop_table`, `drop_column` or `drop_index`,
or any change to `users`, `services`, `bookings` or `service_categories`.** A normal
migration for this stage only adds the one table.

If it looks right, apply it and check:

```powershell
flask --app app db upgrade
flask --app app db-stats
```

Your users, services, categories and bookings stay exactly as they were. Commit the
new file in `migrations\versions` to Git.

### 3. Create a provider and link services to it

You type the password; it is never stored in code. Service names are the "slugs"
from the service page address, for example `leak-detection-pipe-repair`.

```powershell
flask --app app create-provider --email provider1@example.com --name "Pat Provider" --service leak-detection-pipe-repair
flask --app app provider-services --email provider1@example.com
```

Add or remove services later:

```powershell
flask --app app provider-services --email provider1@example.com --add bathroom-fixture-installation
flask --app app provider-services --email provider1@example.com --remove bathroom-fixture-installation
```

Give providers to Pending bookings that were made before one existed (safe to repeat):

```powershell
flask --app app assign-pending
```

### 4. Run the tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

Eleven test files run, **478 tests** in total: `test_stage1.py` (36), `test_database.py` (43),
`test_search_logic.py` (11), `test_security_logic.py` (16), `test_auth.py` (64),
`test_booking_rules.py` (40), `test_bookings.py` (81), `test_provider.py` (103),
`test_query_result_handling.py` (5), `test_admin_rules.py` (19) and `test_admin.py` (60).
Every test uses its own temporary database in your Windows temp folder, CSRF protection
stays on, and your real `instance\fixnear.db` is never touched. No existing test was
changed or removed in Stage 7.

Run one file, one class or one test:

```powershell
python -m unittest tests.test_admin -v
python -m unittest tests.test_admin.AdminAuthorizationTests -v
python -m unittest tests.test_admin_rules -v
```

### 5. Start the app

```powershell
python app.py
```

Open <http://127.0.0.1:5000>. Stop with `Ctrl+C`.

## Verify Stage 7 manually (checklist)

Use the administrator you made with `create-admin`. Use a second (private) window for a customer.

- [ ] Log in as the admin. **Dashboard** numbers match what you know (users, customers, providers, services, bookings, pending, completed). Make a booking as a customer, reload: the numbers go up.
- [ ] **Users:** you see everyone with role and status. Search for part of an email; filter by role and status. Your own row says "This is you" and has no button.
- [ ] Deactivate the test customer. In their window, reload: they are logged out and cannot log in. Activate them again: they can.
- [ ] **Services:** every service is listed with its booking count. **Hide** a service: it disappears from the public Services page and its booking page; a customer's existing booking for it is still visible. **Show** it again.
- [ ] Try to delete a service that has a booking: it is refused with an explanation. Create a new service, then delete it: it works.
- [ ] Create a category, edit its name, then delete it. Try to delete a category that still has services: refused.
- [ ] Try bad input: price `-5`, address `Bad Address`, an empty name: each gives a clear message and saves nothing.
- [ ] **Bookings:** every booking shows reference, customer, provider (or Unassigned), service and status. Filter by status, service and provider; search by part of a reference and by a customer's name.
- [ ] As the customer, open `/admin/users`: "Access denied". As a provider: the same. Logged out: you are sent to the login page.
- [ ] Customer booking and provider Jobs pages still work as before. Resize below 768 px: the admin tables scroll sideways inside their box and nothing overflows the page.

If anything fails, copy the **complete** error text and send it to me.

## Verify Stage 6 manually (checklist)

Use **two browser windows** (one normal, one private) so you can be a customer and a provider at the same time.

- [ ] Create a provider with `create-provider` (above) linked to `leak-detection-pipe-repair`, then log in as them. The dashboard shows "You offer: Leak Detection & Pipe Repair" and zeros everywhere. The menu has **Jobs** but no "My bookings".
- [ ] A provider with **no** linked services sees "No services linked to your account yet".
- [ ] As a customer, book **Leak Detection & Pipe Repair** for a future date at 10:00. The confirmation says the request was sent to **Pat Provider**.
- [ ] As the provider, the request appears under **Waiting for your response**. Open it: you see the address, phone and problem description, but not the customer's email.
- [ ] As a second customer, book the same service at the same date and 10:00 (or 11:00): you are told no provider is available. Try 12:00 or later: it works (if you have only one provider, it shows up for them too).
- [ ] As the provider, click **Accept**: the status becomes Accepted. As the customer, reload the booking: it shows Accepted and the provider's name.
- [ ] Click **Start job**, then **Mark completed** as the provider. The customer's dashboard shows Completed 1, and the customer cannot cancel a job in progress.
- [ ] Book another request and click **Reject**: the customer sees "rejected", and can book the same time again.
- [ ] Press the browser's Back button after a refresh or double click on **Accept**: you are never given an error page, and the status does not change twice.
- [ ] As the customer, open `/provider/dashboard`: "Access denied". As the provider, open `/bookings`: "Access denied".
- [ ] As a second provider (linked to a different service), paste the first provider's job address `/provider/bookings/FN-...`: "Page not found".
- [ ] Customer pages, search, categories and service pages look and work as before. Resize below 768 px: the provider cards and buttons stay readable.

If anything fails, copy the **complete** error text and send it to me.

## Verify Stage 5 manually (checklist)

Tick all of these before Stage 6. Use a customer account (register one if needed).

- [ ] Open a service page while **logged out**. Click **Book this service**: you reach the login page. Choose **Create a free account**, sign up, and you land on the booking form for that service.
- [ ] The form shows the service name and starting price, your name pre-filled, and a date picker that does not allow past days.
- [ ] Submit with a few things wrong (past date, phone `abc`, empty address): each gives a clear message, and what you typed is kept.
- [ ] Submit a correct booking: you see the confirmation page with a reference like `FN-7K4M-9QXT` and the status **Pending**.
- [ ] Press the browser's **Back** button and submit again, or double-click **Request booking**: you are not given a second booking.
- [ ] **My bookings** and the **dashboard** both show the booking; the dashboard counts changed (Total 1, Pending 1).
- [ ] Open the booking: the progress line shows Pending, with the address, phone and problem you entered.
- [ ] Book the same service at the same date and time again: it is refused with a clear message.
- [ ] **Cancel** the booking (add a reason): the status becomes Cancelled, the reason is shown, and Cancel is no longer offered.
- [ ] Stop the app (`Ctrl+C`), start it again: the booking is still listed.
- [ ] Register a second customer in a private window. Paste the first customer's booking address (`/bookings/FN-...`) into the second customer's browser: you get the "Page not found" page.
- [ ] Log in as the admin (from `create-admin`) and open `/bookings` or a service's `/book` page: "Access denied".
- [ ] Home, search (`leak`), category filters and service pages look and work as before.
- [ ] Resize below 768 px: the forms, booking cards and dashboard stay readable with no sideways scrolling.

If anything fails, copy the **complete** error text and send it to me.

## Verify Stage 4 (checklist)

The Stage 4 checks, kept for reference.

- [ ] `pip install -r requirements.txt` finishes without errors.
- [ ] `db migrate` creates a migration that adds only `users`; `db upgrade` succeeds.
- [ ] `create-admin` works, and `list-users` shows the admin with role `admin`.
- [ ] The test command ends with `OK` (285 tests, which includes Stage 5).
- [ ] **Register** a new account at `/register`: you land on the customer dashboard and see a welcome message.
- [ ] Registering the same email again (try different letter case) shows an error.
- [ ] A weak password (`short1`) shows a clear error and creates no account.
- [ ] **Log out** with the button in the menu; the dashboard is now closed. Press the browser's Back button: no private page shows.
- [ ] **Log in** with a wrong password: "Invalid email or password." Right password: you reach the dashboard.
- [ ] While logged out, open `/customer/dashboard`: you go to the login page, then back to the dashboard after login.
- [ ] Open `/login?next=https://example.org` and log in: you stay on FixNear.
- [ ] As a customer, open `/admin/dashboard`: the "Access denied" page appears.
- [ ] Log in as the admin and open `/customer/dashboard`: also "Access denied". `/admin/dashboard` works.
- [ ] Home, search (`leak`), category filters and a service page look the same as before.
- [ ] Resize the browser below 768 px wide: the menu button opens Log in / Create account.

If anything fails, copy the **complete** error text and send it to me.

## Project structure (new or changed in Stages 4 to 7)

```text
FixNear/
  extensions.py           db, migrate, csrf, login_manager
  cli.py                  seed-db, db-stats, create-admin, list-users
  models/user.py          User model, roles, login session loader
  forms/auth.py           Registration and login forms (Flask-WTF)
  routes/auth.py          /register, /login, /logout
  routes/dashboard.py     Role-protected dashboards (placeholders)
  services/accounts.py    Create users, check logins
  services/passwords.py   Password rules and hashing
  services/security.py    Email cleanup and safe redirects
  services/permissions.py role_required() access check
  models/booking.py       Booking model (status check, unique reference, optional provider)
  services/booking_rules.py  Statuses, transitions, cancellation, dates, phone, references (no database)
  services/bookings.py    Create, read and cancel bookings (all rules enforced here)
  forms/booking.py        Booking and cancel forms (no status/provider/price fields)
  routes/bookings.py      Customer booking pages
  routes/provider.py      Provider jobs, details and actions
  routes/admin.py         Admin pages (users, services, categories, bookings)
  forms/admin.py          Category and service forms
  services/admin.py       Dashboard counts, user management, all-bookings view
  services/catalog_admin.py  Safe create/edit/hide/delete of categories and services
  services/admin_rules.py Pagination, address checks, user-safety rule (no database)
  templates/admin/        Admin pages
  models/provider.py      provider_services table (which provider offers which service)
  services/scheduling.py  Conflict checks and choosing a provider
  services/provider_bookings.py  What a provider can see and do
  services/providers.py   Linking providers to services
  services/errors.py      Shared booking and scheduling errors
  templates/provider/     Jobs list and job details
  templates/bookings/     Form, confirmation, details, history, cancel
  templates/auth/         Login and register pages
  templates/dashboard/    Customer, provider and admin placeholders
  templates/partials/_form_field.html   Reusable form field
  tests/test_auth.py, tests/test_security_logic.py
  tests/test_booking_rules.py, tests/test_bookings.py, tests/test_provider.py
  tests/test_admin_rules.py, tests/test_admin.py
```

## Troubleshooting

- **"Access denied" on `/admin/...`**: the account is not an active administrator. Create one with `flask --app app create-admin`.
- **A service "cannot be deleted"**: it has bookings. Use **Hide** instead; hidden services stay in the database.
- **"You cannot deactivate your own account"**: by design. Ask another administrator.

- **`no such table: provider_services`**: run `flask --app app db upgrade`.
- **`The provider_services table does not exist yet`** from a provider command: run both `db migrate` and `db upgrade` first.
- **A booking stays "Not assigned yet"**: no active provider offers that service. Link one with `provider-services --add`, then run `assign-pending`.
- **"No provider is available for that date and time"**: every provider who offers the service already has a job within 2 hours of that time. Choose another time, or link another provider.
- **A provider says they cannot accept a job**: they already have an accepted or in-progress job within 2 hours of it.

- **`no such table: bookings`**: run `flask --app app db upgrade`.
- **`no such column: services.is_available`**: the migration was generated but not applied. Run `flask --app app db upgrade`.
- **The migration fails with "Cannot add a NOT NULL column with default value NULL"**: the generated file is missing `server_default` on `is_available`. Send me the file; do not apply it.
- **A booking is refused as "already passed" or "in the past" at the wrong time**: set `BOOKING_UTC_OFFSET_MINUTES` in `.env` to your local offset from UTC in minutes (India is 330).
- **"This form has expired" when booking**: reload the booking page (it creates a fresh form) and submit again.

- **`ModuleNotFoundError: No module named 'flask_login'` (or `flask_wtf`, `email_validator`)**: run step 1 again with the virtual environment active.
- **`no such table: users`**: run `flask --app app db upgrade`.
- **`The users table does not exist yet` from `create-admin`**: run both `db migrate` and `db upgrade` first.
- **`Target database is not up to date`** when migrating: run `flask --app app db upgrade`, then migrate again.
- **Pages say "Request could not be verified"**: the form was open too long or cookies are blocked. Reload the page and try again.
- **Reset a forgotten admin password (development only):** stop the app, delete the user row with a database tool, and run `create-admin` again. There is no password reset feature yet.

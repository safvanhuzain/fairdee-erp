# Fairdee Finance (v1)

Django + PostgreSQL finance foundation aligned with `django_postgres_user_architecture.pdf`:

- **Custom user** (`accounts.User`): email login, optional `company`, `metadata` JSON for flexible fields.
- **`core.Company`**: tenant / legal entity; `metadata` JSON for org-level config.
- **`access.RoleProfile`**: links a named finance role to Django `Group` (assign model permissions on the group in Admin).
- **`finance`**: `Invoice`, `JournalEntry`, `JournalLine` stubs for GL-style data.
- **`desk`**: Server-rendered workspace at `/app/` — sidebar, **Company** and **Users** list views for now (more Frappe-style doctypes added incrementally), login — visually aligned with a typical Frappe/ERPNext desk (custom HTML/CSS, not a fork of Frappe assets).

## Quick start (SQLite, no Docker)

The project **defaults to SQLite** so `migrate` / `createsuperuser` work without PostgreSQL. Optional: `export USE_SQLITE=false` only when using Postgres with `USE_POSTGRES=1`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # use email when prompted
python manage.py runserver
```

- **Desk (Frappe-style UI):** http://127.0.0.1:8000/app/ (redirects from `/`; sign in at `/login/`)
- **Users (desk):** http://127.0.0.1:8000/app/accounts/user/ — requires Django permission **`accounts.view_user`** to open the list. The **Add user** button and create form require **`accounts.add_user`**. Grant these on a user’s **group** in Admin (Auth → Groups) or assign them directly on the user. Superusers always have access.
- Admin: http://127.0.0.1:8000/admin/
- Health: http://127.0.0.1:8000/api/v1/health/

## PostgreSQL (recommended for production / JSONB)

```bash
docker compose up -d
source .venv/bin/activate
pip install -r requirements.txt
export USE_POSTGRES=1
export USE_SQLITE=false
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Connection defaults match `docker-compose.yml` (`fairdee` / `fairdee` on `localhost:5432`). Override with `POSTGRES_*` env vars (see `.env.example`).

### Optional GIN indexes (PostgreSQL)

Migrations stay DB-agnostic. On PostgreSQL, you can add GIN indexes on `metadata` JSONB columns for heavy JSON querying:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS accounts_user_metadata_gin
  ON accounts_user USING gin (metadata jsonb_path_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS core_company_metadata_gin
  ON core_company USING gin (metadata jsonb_path_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS finance_invoice_metadata_gin
  ON finance_invoice USING gin (metadata jsonb_path_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS finance_journalentry_metadata_gin
  ON finance_journalentry USING gin (metadata jsonb_path_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS finance_journalline_metadata_gin
  ON finance_journalline USING gin (metadata jsonb_path_ops);
```

## Roles and permissions (v1)

1. In Admin, create **Groups** (e.g. `Finance Head`, `AP Clerk`).
2. For each group, assign **Permissions** on models (invoices, journal entries, users, etc.).
3. Optionally create a **Role profile** pointing at that group for a human-readable slug and optional company scope.
4. Assign users to groups.

A dedicated “permission matrix” UI can be added later; v1 uses Django’s built-in auth tables plus `RoleProfile` for documentation and future extensions.

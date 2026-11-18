"""Create a fresh YAAN database in its initial state (no business data).

    python scripts/clone_database.py yaan_copy
    python scripts/clone_database.py yaan_copy --admin-password "Str0ng#Pass2026"
    python scripts/clone_database.py yaan_copy --server-url postgresql+psycopg://postgres:pw@localhost:5432/postgres
    python scripts/clone_database.py yaan_copy --drop-existing

What "initial state" means here:
  * every table, index, constraint and extension, built by running all Alembic migrations;
  * the reference/lookup rows the migrations insert (trip types, expense categories, compliance types, ...);
  * one Super Admin so you can log in (skip with --no-admin).
Roles and their permissions are defined in code (app/core/permissions.py), not in tables, so they come with the app.
Nothing is copied from the source database: no vendors, customers, employees, trips, users or logs.

Run from the backend folder with the virtualenv active. The new database is NOT used by the app until you point
DATABASE_URL (in .env) at it.
"""
import argparse
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="name of the new database, e.g. yaan_copy")
    ap.add_argument("--server-url", help="connection URL of a user allowed to CREATE DATABASE "
                    "(default: DATABASE_URL from .env, i.e. the app user)")
    ap.add_argument("--drop-existing", action="store_true", help="drop the database first if it already exists")
    ap.add_argument("--no-admin", action="store_true", help="do not create a Super Admin")
    ap.add_argument("--admin-username", default="superadmin")
    ap.add_argument("--admin-email", default="superadmin@yaan.local")
    ap.add_argument("--admin-password", help="default: a random one, printed once at the end")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", args.name):
        raise SystemExit("Database name may only contain letters, digits and underscores.")

    from app.core.config import get_settings
    source = make_url(args.server_url or get_settings().database_url)
    target = source.set(database=args.name)
    owner = source.username
    plain = lambda u: u.set(drivername="postgresql").render_as_string(hide_password=False)  # psycopg DSN

    # 1. create the empty database
    try:
        create_database(plain(source.set(database="postgres")), args, owner)
    except psycopg.errors.InsufficientPrivilege:
        raise SystemExit(
            f"The database user '{owner}' is not allowed to create databases.\n"
            "Re-run with --server-url for an administrator account, e.g.\n"
            f"  python scripts/clone_database.py {args.name} --server-url postgresql+psycopg://postgres:<password>@localhost:5432/postgres")
    _after_create(args, target)


def create_database(dsn: str, args, owner: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (args.name,)).fetchone()
        if exists and not args.drop_existing:
            raise SystemExit(f"Database '{args.name}' already exists. Use --drop-existing to replace it.")
        if exists:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(args.name)))
            print(f"Dropped existing database {args.name}")
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(args.name), sql.Identifier(owner)))
        print(f"Created database {args.name}")


def _after_create(args, target) -> None:
    # 2. build the schema + lookup rows with the project's own migrations
    env = {**os.environ, "DATABASE_URL": target.render_as_string(hide_password=False)}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)

    # 3. first Super Admin
    password = None
    if not args.no_admin:
        os.environ["DATABASE_URL"] = env["DATABASE_URL"]
        from app.core.security import hash_password
        from app.db.session import SessionLocal
        from app.models import Role, User
        from app.services.auth_service import now
        password = args.admin_password or secrets.token_urlsafe(12) + "#9a"
        with SessionLocal() as db:
            db.add(User(first_name="Super", last_name="Admin", username=args.admin_username, email=args.admin_email,
                        role=Role.SUPER_ADMIN, password_hash=hash_password(password), initial_setup_completed_at=now()))
            db.commit()

    print(f"\nDone. New database: {args.name}")
    if password:
        print(f"Super Admin login: {args.admin_username} / {password}  (change it after first login)")
    print(f"To use it, set in backend/.env:\n  DATABASE_URL={target.render_as_string(hide_password=False)}")


if __name__ == "__main__":
    main()

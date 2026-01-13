#!/usr/bin/env python3
"""Seed the `template_contents` table with the workspace `template.yml`.

Behavior:
- Reads DB connection info from .env in the repo root.
- Ensures at least one `users` and `templates` row exist (creates minimal records if needed).
- Inserts a `template_contents` row with the contents of `template.yml` and prints the new ID.

Usage: .venv/bin/python3.14 scripts/seed_template_content.py
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
TEMPLATE_PATH = ROOT / "template.yml"


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def get_conn(env: dict):
    return psycopg2.connect(
        dbname=env.get("DB_NAME", "dozilab"),
        user=env.get("DB_USER", "postgres"),
        password=env.get("DB_PASSWORD", "postgres"),
        host=env.get("DB_HOST", "localhost"),
        port=int(env.get("DB_PORT", 5432)),
    )


def ensure_user(cur) -> str:
    cur.execute("SELECT id FROM users LIMIT 1")
    row = cur.fetchone()
    if row:
        return row[0]
    new_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO users (id, external_id, created_at, last_login_at) VALUES (%s, %s, %s, %s)",
        (new_id, "seed-user", datetime.now(timezone.utc), datetime.now(timezone.utc)),
    )
    return new_id


def ensure_template(cur, owner_id: str) -> str:
    cur.execute("SELECT id FROM templates LIMIT 1")
    row = cur.fetchone()
    if row:
        return row[0]
    new_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO templates (id, name, description, owner_id, repo_url, visibility, approval_status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (new_id, "seed-template", "Seeded template for local testing", owner_id, "seed://local", 'PRIVATE', 'APPROVED', datetime.now(timezone.utc), datetime.now(timezone.utc)),
    )
    return new_id


def insert_template_content(cur, template_id: str, content: str, version: str = "v1") -> str:
    new_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO template_contents (id, template_id, version, content, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (new_id, template_id, version, content, datetime.now(timezone.utc), datetime.now(timezone.utc)),
    )
    return cur.fetchone()[0]


def main() -> None:
    env = load_env(ENV_PATH)
    if not TEMPLATE_PATH.exists():
        print(f"template.yml not found at {TEMPLATE_PATH}")
        raise SystemExit(1)
    content = TEMPLATE_PATH.read_text()

    conn = get_conn(env)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            user_id = ensure_user(cur)
            template_id = ensure_template(cur, user_id)
            new_id = insert_template_content(cur, template_id, content, version="v1")
        conn.commit()
        print(new_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

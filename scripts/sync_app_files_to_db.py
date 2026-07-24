#!/usr/bin/env python3
"""Sync template files for an existing app from disk to the local DB.

Usage:
  uv run python scripts/sync_app_files_to_db.py <template-name> <app-dir>

Examples:
  uv run python scripts/sync_app_files_to_db.py \
    "Ansible Multi-User Ubuntu" \
    ../appstore-apps/ansible_multiuser

  uv run python scripts/sync_app_files_to_db.py \
    "Ansible PostgreSQL Group DB" \
    ../appstore-apps/ansible_postgres_group_db

Why this exists:
  add_*.py scripts create a new template from scratch but fail on the second
  run (template name conflict). After editing a playbook on disk you don't
  want to delete + recreate the template every time — that loses Stack-IDs,
  course bindings, and history. This script just refreshes the *files* of
  the currently active version, matched by file_name. Bytes change, IDs
  don't.
"""
import sys
from pathlib import Path

# Make src/ importable so we can reuse the model + session.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import SessionLocal
from src.models.template import Template
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    template_name = sys.argv[1]
    app_dir = Path(sys.argv[2]).resolve()

    if not app_dir.is_dir():
        print(f"✗ App-Dir not found: {app_dir}")
        sys.exit(1)

    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.name == template_name).first()
        if not template:
            print(f"✗ Template not found in DB: {template_name!r}")
            sys.exit(1)

        # Pick the latest version (sort by created_at desc).
        version = (
            db.query(TemplateVersion)
            .filter(TemplateVersion.template_id == template.id)
            .order_by(TemplateVersion.created_at.desc())
            .first()
        )
        if not version:
            print(f"✗ No version exists for template {template_name!r}")
            sys.exit(1)

        print(f"Template:   {template.name} (id={template.id})")
        print(f"Version:    {version.version} (id={version.id})")
        print(f"Source dir: {app_dir}")
        print()

        files_in_db = (
            db.query(TemplateVersionFile)
            .filter(TemplateVersionFile.template_version_id == version.id)
            .all()
        )
        by_name = {f.file_name: f for f in files_in_db}

        # Recursively look for any file matching a DB file_name in the app dir.
        # Match by basename only — file_name in the DB is e.g. "main.yml",
        # not "playbooks/main.yml".
        disk_by_name: dict[str, Path] = {}
        for p in app_dir.rglob("*"):
            if p.is_file() and p.name in by_name:
                disk_by_name[p.name] = p

        updated = 0
        skipped_missing: list[str] = []

        for name, db_row in by_name.items():
            disk_path = disk_by_name.get(name)
            if not disk_path:
                skipped_missing.append(name)
                continue

            new_content = disk_path.read_text(encoding="utf-8")
            if new_content == (db_row.content or ""):
                print(f"  = {name}  (unchanged)")
                continue

            old_size = len(db_row.content or "")
            db_row.content = new_content
            db_row.file_size = len(new_content.encode())
            print(f"  ✓ {name}  ({old_size} → {db_row.file_size} bytes)  from {disk_path.relative_to(app_dir)}")
            updated += 1

        if skipped_missing:
            print()
            print("⚠ Files in DB but not on disk (left untouched):")
            for n in skipped_missing:
                print(f"    {n}")

        db.commit()
        print()
        print("=" * 60)
        print(f"Updated {updated} file(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Upload alle Dateien eines Templates in die DB via API.

Usage:
  python upload_template.py <template_version_id> <token>

Beispiel:
  python upload_template.py 48fc1abb-495f-411a-b221-819e1242be38 eyJhbGc...
"""
import sys
import os
import httpx
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
TEMPLATE_DIR = Path(__file__).parent.parent / "appstore-apps" / "ansible_multiuser"

# Mapping: (ordner, dateiname) → (file_type, is_primary, order)
FILE_MAP = {
    "app.yaml":                           ("APP_MANIFEST",      False, 0),
    "heat/main.yaml":                     ("HEAT_TEMPLATE",     True,  0),
    "playbooks/main.yml":                 ("ANSIBLE_PLAYBOOK",  False, 1),
    "scripts/check_student_setup.sh":     ("SHELL_SCRIPT",      False, 1),
    "scripts/reset_password.sh":          ("SHELL_SCRIPT",      False, 2),
    "files/bashrc":                       ("CONFIG_FILE",       False, 1),
    "files/motd":                         ("CONFIG_FILE",       False, 2),
}


def upload(template_version_id: str, token: str):
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch existing files to detect duplicates
    existing = {}
    resp = httpx.get(
        f"{BASE_URL}/api/v1/template-versions/{template_version_id}/files",
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 200:
        for f in resp.json().get("data", []):
            key = f["file_path"]
            # Keep only the oldest entry per path (avoid duplicate keys)
            if key not in existing:
                existing[key] = f["id"]

    for rel_path, (file_type, is_primary, order) in FILE_MAP.items():
        full_path = TEMPLATE_DIR / rel_path
        if not full_path.exists():
            print(f"  ⚠ Nicht gefunden: {full_path} — übersprungen")
            continue

        content = full_path.read_text(encoding="utf-8")
        payload = {
            "template_version_id": template_version_id,
            "file_name":           full_path.name,
            "file_type":           file_type,
            "file_path":           rel_path,
            "content":             content,
            "file_size":           len(content.encode()),
            "is_primary":          is_primary,
            "order":               order,
        }

        if rel_path in existing:
            # Update existing file
            file_id = existing[rel_path]
            resp = httpx.put(
                f"{BASE_URL}/api/v1/template-version-files/{file_id}",
                json=payload,
                headers=headers,
                timeout=30,
            )
            action = "updated"
        else:
            # Create new file
            resp = httpx.post(
                f"{BASE_URL}/api/v1/template-version-files",
                json=payload,
                headers=headers,
                timeout=30,
            )
            action = "created"

        if resp.status_code in (200, 201):
            print(f"  ✓ {rel_path} ({file_type}) [{action}]")
        else:
            print(f"  ✗ {rel_path} → {resp.status_code}: {resp.text[:200]}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    version_id, token = sys.argv[1], sys.argv[2]
    print(f"Uploading to template version: {version_id}")
    upload(version_id, token)
    print("Fertig.")

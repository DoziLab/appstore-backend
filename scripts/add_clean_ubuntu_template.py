#!/usr/bin/env python3
"""Script to add clean_ubuntu (Student VM) template to database."""

import sys
import subprocess
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import SessionLocal, init_db
from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User

# Initialize database models
init_db()


def run_migration():
    """Run pending Alembic migrations."""
    print("\n" + "="*80)
    print("🔄 Running database migrations...")
    print("="*80 + "\n")
    
    try:
        # Run alembic upgrade head
        result = subprocess.run(
            ["python", "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✓ Migrations applied successfully")
            if result.stdout:
                print(result.stdout)
        else:
            print(f"❌ Migration failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error running migrations: {e}")
        return False
    
    return True


def main():
    """Add clean_ubuntu template to database with all files."""
    # First, run migrations to add APP_MANIFEST enum value
    if not run_migration():
        print("\n⚠️  Continuing anyway, enum value might already exist...")
    
    db = SessionLocal()
    
    try:
        # Get first user (or you can specify a user ID)
        user = db.query(User).first()
        if not user:
            print("ERROR: No users found in database. Please create a user first.")
            return
        
        print(f"Using user: {user.id}")
        
        # === 1. Create Template ===
        template = Template(
            name="DoziLab Student VM",
            description="Deploy a student VM with username/password SSH login and workdir landing. Multi-user support with password policies.",
            owner_id=user.id,
            repo_url="https://github.com/dozilab/appstore-templates",
            visibility=TemplateVisibility.PUBLIC,
            approval_status=TemplateApprovalStatus.APPROVED
        )
        db.add(template)
        db.flush()  # Get ID without committing
        
        print(f"✓ Created template: {template.id}")
        print(f"  Name: {template.name}")
        
        # === 2. Read file contents first to extract version ===
        base_path = Path(__file__).parent.parent / "appstore-apps" / "clean_ubuntu"
        
        app_yaml_content = (base_path / "app.yaml").read_text()
        heat_yaml_content = (base_path / "heat.yaml").read_text()
        cloud_init_content = (base_path / "cloud-init.yaml").read_text()
        
        print(f"✓ Loaded files from: {base_path}")
        
        # Parse app.yaml to extract version
        import yaml
        app_manifest = yaml.safe_load(app_yaml_content)
        app_version = app_manifest.get('app', {}).get('version', '0.1.0')
        
        # === 3. Create Template Version ===
        version = TemplateVersion(
            template_id=template.id,
            version=app_version,  # Use version from app.yaml
            git_commit_sha="v0.2.0-student-vm",  # Git tag/commit
            is_active=True
        )
        db.add(version)
        db.flush()
        
        print(f"✓ Created version: {version.id} (v{app_version})")
        
        # === 4. Create app.yaml file (WICHTIG für Parameter!) ===
        app_file = TemplateVersionFile(
            template_version_id=version.id,
            file_name="app.yaml",
            file_type=FileType.APP_MANIFEST,  # ← Wichtig!
            file_path="clean_ubuntu/app.yaml",
            content=app_yaml_content,
            file_size=len(app_yaml_content.encode('utf-8')),
            description="Application manifest with parameter definitions",
            is_primary=False,
            order=0
        )
        db.add(app_file)
        print(f"✓ Created app.yaml file (APP_MANIFEST)")
        
        # === 5. Create heat.yaml file ===
        heat_file = TemplateVersionFile(
            template_version_id=version.id,
            file_name="heat.yaml",
            file_type=FileType.HEAT_TEMPLATE,
            file_path="clean_ubuntu/heat.yaml",
            content=heat_yaml_content,
            file_size=len(heat_yaml_content.encode('utf-8')),
            description="Main Heat template for multi-student VM deployment",
            is_primary=True,  # Primary deployment file
            order=1
        )
        db.add(heat_file)
        print(f"✓ Created heat.yaml file (HEAT_TEMPLATE)")
        
        # === 6. Create cloud-init.yaml file ===
        cloud_init_file = TemplateVersionFile(
            template_version_id=version.id,
            file_name="cloud-init.yaml",
            file_type=FileType.CLOUD_INIT,
            file_path="clean_ubuntu/cloud-init.yaml",
            content=cloud_init_content,
            file_size=len(cloud_init_content.encode('utf-8')),
            description="Cloud-init script for multi-user setup with password policies",
            is_primary=False,
            order=2
        )
        db.add(cloud_init_file)
        print(f"✓ Created cloud-init.yaml file (CLOUD_INIT)")
        
        # === 7. Commit all changes ===
        db.commit()
        
        print("\n" + "="*80)
        print("✅ SUCCESS! Template created successfully!")
        print("="*80)
        print(f"\nTemplate ID: {template.id}")
        print(f"Version ID:  {version.id}")
        print(f"\nFiles:")
        print(f"  1. app.yaml       (APP_MANIFEST)  - {len(app_yaml_content):,} bytes")
        print(f"  2. heat.yaml      (HEAT_TEMPLATE) - {len(heat_yaml_content):,} bytes (primary)")
        print(f"  3. cloud-init.yaml (CLOUD_INIT)   - {len(cloud_init_content):,} bytes")
        print("\n📦 Parameters from app.yaml:")
        print("   - network, external_network, image, flavor")
        print("   - student_username, student_password (secret!)")
        print("   - force_password_change (boolean)")
        print("   - workdir, page_title, stack_label")
        print("\n🎉 Frontend kann jetzt Parameter über API abrufen:")
        print(f"   GET /api/v1/template-versions/{version.id}?include_parameters=true")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
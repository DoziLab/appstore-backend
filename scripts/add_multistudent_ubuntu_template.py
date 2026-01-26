#!/usr/bin/env python3
"""Script to add multistudent_ubuntu template to database."""
 
import sys
import yaml
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
 
 
def main():
    """Add multistudent_ubuntu template to database with all files."""
    db = SessionLocal()
    try:
        # Get first user (or you can specify a user ID)
        user = db.query(User).first()
        if not user:
            print("ERROR: No users found in database. Please create a user first.")
            return
        print(f"Using user: {user.id}")
        # === 1. Read file contents first to extract metadata ===
        base_path = Path(__file__).parent.parent / "appstore-apps" / "multistudent_ubuntu"
        app_yaml_content = (base_path / "app.yaml").read_text()
        heat_yaml_content = (base_path / "heat" / "main.yaml").read_text()
        cloud_init_content = (base_path / "cloud-init" / "user-data.yaml").read_text()
        print(f"✓ Loaded files from: {base_path}")
        # Parse app.yaml to extract metadata
        app_manifest = yaml.safe_load(app_yaml_content)
        app_info = app_manifest.get('app', {})
        app_name = app_info.get('name', 'multiuser-ubuntu')
        app_label = app_info.get('label', 'Multi-User Ubuntu')
        app_version = app_info.get('version', '1.0.0')
        app_description = app_info.get('description', '')
        # === 2. Create Template ===
        template = Template(
            name=app_label,  # Use label from app.yaml
            description=app_description.strip() if app_description else "Multi-user Ubuntu VM for courses",
            owner_id=user.id,
            repo_url="https://github.com/dozilab/appstore-templates",
            icon_url="mdi:account-multiple",  # Material Design Icon for multi-user
            visibility=TemplateVisibility.PUBLIC,
            approval_status=TemplateApprovalStatus.APPROVED
        )
        db.add(template)
        db.flush()  # Get ID without committing
        print(f"✓ Created template: {template.id}")
        print(f"  Name: {template.name}")
        # === 3. Create Template Version ===
        version = TemplateVersion(
            template_id=template.id,
            version=app_version,  # Use version from app.yaml
            git_commit_sha=f"v{app_version}-multistudent",
            is_active=True
        )
        db.add(version)
        db.flush()
        print(f"✓ Created version: {version.id} (v{app_version})")
        # === 4. Create app.yaml file (APP_MANIFEST) ===
        app_file = TemplateVersionFile(
            template_version_id=version.id,
            file_name="app.yaml",
            file_type=FileType.APP_MANIFEST,
            file_path="multistudent_ubuntu/app.yaml",
            content=app_yaml_content,
            file_size=len(app_yaml_content.encode('utf-8')),
            description="Application manifest with parameter definitions",
            is_primary=False,
            order=0
        )
        db.add(app_file)
        print(f"✓ Created app.yaml file (APP_MANIFEST)")
        # === 5. Create heat/main.yaml file (HEAT_TEMPLATE) ===
        heat_file = TemplateVersionFile(
            template_version_id=version.id,
            file_name="main.yaml",
            file_type=FileType.HEAT_TEMPLATE,
            file_path="multistudent_ubuntu/heat/main.yaml",
            content=heat_yaml_content,
            file_size=len(heat_yaml_content.encode('utf-8')),
            description="Main Heat template for multi-student VM deployment",
            is_primary=True,  # Primary deployment file
            order=1
        )
        db.add(heat_file)
        print(f"✓ Created heat/main.yaml file (HEAT_TEMPLATE)")
        # === 6. Create cloud-init/user-data.yaml file (CLOUD_INIT) ===
        cloud_init_file = TemplateVersionFile(
            template_version_id=version.id,
            file_name="user-data.yaml",
            file_type=FileType.CLOUD_INIT,
            file_path="multistudent_ubuntu/cloud-init/user-data.yaml",
            content=cloud_init_content,
            file_size=len(cloud_init_content.encode('utf-8')),
            description="Cloud-init script for multi-user setup with password policies",
            is_primary=False,
            order=2
        )
        db.add(cloud_init_file)
        print(f"✓ Created cloud-init/user-data.yaml file (CLOUD_INIT)")
        # Commit all changes
        db.commit()
        print("\n" + "="*80)
        print("✅ SUCCESS! Template created successfully!")
        print("="*80)
        print(f"\nTemplate ID: {template.id}")
        print(f"Version ID:  {version.id}")
        print(f"\nFiles:")
        print(f"  1. app.yaml                    (APP_MANIFEST)  - {app_file.file_size:,} bytes")
        print(f"  2. heat/main.yaml              (HEAT_TEMPLATE) - {heat_file.file_size:,} bytes (primary)")
        print(f"  3. cloud-init/user-data.yaml   (CLOUD_INIT)   - {cloud_init_file.file_size:,} bytes")
        # Extract and show parameter count
        parameters = app_manifest.get('parameters', [])
        print(f"\n📦 Parameters from app.yaml:")
        print(f"   Total: {len(parameters)} parameters")
        visible_params = [p for p in parameters if not p.get('hidden', False)]
        hidden_params = [p for p in parameters if p.get('hidden', False)]
        print(f"   Visible: {len(visible_params)}")
        print(f"   Hidden: {len(hidden_params)}")
        # Show parameter steps
        steps = {}
        for param in visible_params:
            step = param.get('step', 'other')
            steps[step] = steps.get(step, 0) + 1
        if steps:
            print(f"\n   Steps:")
            for step, count in steps.items():
                print(f"     • {step}: {count} parameters")
        print(f"\n🎉 Frontend kann jetzt Parameter über API abrufen:")
        print(f"   GET /api/v1/template-versions/{version.id}?include_parameters=true")
        print("\n")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()
 
 
if __name__ == "__main__":
    main()
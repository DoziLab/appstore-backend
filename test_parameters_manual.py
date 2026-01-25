"""Manual test script for template parameters endpoint."""
import sys
from sqlalchemy.orm import Session

# Add src to path
sys.path.insert(0, '/Users/i589645/Desktop/appstore-backend')

from src.core.database import SessionLocal
from src.services.template_version_file_service import TemplateVersionFileService
from src.repositories.template_version_repository import TemplateVersionRepository

def test_parameters():
    """Test parameter extraction from template version."""
    db: Session = SessionLocal()
    try:
        # Get first template version
        version_repo = TemplateVersionRepository(db)
        versions = version_repo.get_all()
        
        if not versions:
            print("❌ No template versions found in database!")
            return
        
        version = versions[0]
        print(f"✅ Found template version: {version.id}")
        print(f"   Version number: {version.version}")
        print(f"   Template ID: {version.template_id}")
        
        # Test parameter extraction
        service = TemplateVersionFileService(db)
        print(f"\n🔍 Extracting parameters for version {version.id}...")
        
        try:
            params_response = service.get_template_parameters(str(version.id))
            print("\n✅ Successfully extracted parameters!")
            print(f"   Template Version ID: {params_response.template_version_id}")
            print(f"   Number of parameters: {len(params_response.parameters)}")
            
            print("\n📋 Parameter Details:")
            print("=" * 80)
            for param in params_response.parameters:
                print(f"\n  Name: {param.name}")
                print(f"  Type: {param.type}")
                print(f"  Required: {param.required}")
                print(f"  Default: {param.default}")
                print(f"  Description: {param.description[:60]}..." if len(param.description) > 60 else f"  Description: {param.description}")
                
        except Exception as e:
            print(f"❌ Error extracting parameters: {e}")
            import traceback
            traceback.print_exc()
            
    finally:
        db.close()

if __name__ == "__main__":
    test_parameters()

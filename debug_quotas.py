#!/usr/bin/env python3
"""Debug script to test quotas endpoint"""
import asyncio
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_quotas():
    """Test quotas endpoint"""
    try:
        # Test imports
        logger.info("Testing imports...")
        from src.services.openstack_resource_service import OpenstackResourceService
        from src.schemas.openstack_resources import QuotaResponse
        logger.info("✓ Imports successful")
        
        # Test database connection
        logger.info("Testing database connection...")
        from src.core.database import SessionLocal
        db = SessionLocal()
        logger.info("✓ Database connection successful")
        
        # Test service initialization
        logger.info("Testing OpenstackResourceService initialization...")
        service = OpenstackResourceService(db)
        logger.info("✓ Service initialized")
        
        logger.info("\nAll components initialized successfully!")
        logger.info("Now test the actual API call in the browser or with curl")
        
    except Exception as e:
        logger.error(f"✗ Error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if 'db' in locals():
            db.close()

if __name__ == "__main__":
    asyncio.run(test_quotas())

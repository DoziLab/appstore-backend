"""OpenStack connection helper."""

import openstack
from openstack import exceptions
import logging
from src.core.config import get_settings

logger = logging.getLogger(__name__)

def get_openstack_connection(cloud_name: str = "dhbw"):
    """
    Returns an authenticated OpenStack connection using clouds.yaml config.
    
    cloud_name: Name of the cloud from clouds.yaml
    """
    try:
        conn = openstack.connect(cloud=cloud_name)
        # Test connection
        conn.authorize()
        logger.info(f"Connected to OpenStack cloud: {cloud_name}")
        return conn
    except exceptions.ConfigException:
        logger.error(f"Cloud '{cloud_name}' not found. Check clouds.yaml.")
        raise
    except Exception as e:
        logger.error(f"Failed to connect to OpenStack: {e}")
        raise

def get_openstack_connection():
    """
    Connect to OpenStack using clouds.yaml
    """
    cloud_name = "dhbw"  # Name wie in clouds.yaml
    conn = openstack.connect(cloud=cloud_name)
    return conn


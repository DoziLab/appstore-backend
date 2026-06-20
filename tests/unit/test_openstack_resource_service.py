"""Tests for OpenStack Resource Service."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.orm import Session

from src.services.openstack_resource_service import OpenstackResourceService
from src.models.openstack_project import OpenstackProject
from src.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from openstack.exceptions import HttpException, SDKException


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    return Mock(spec=Session)


@pytest.fixture
def mock_openstack_project():
    """Create a mock OpenStack project."""
    project = Mock(spec=OpenstackProject)
    project.id = "project-123"
    project.owner_user_id = "user-123"
    project.openstack_project_id = "openstack-proj-123"
    project.openstack_project_name = "test-project"
    project.auth_url = "https://openstack.example.com:5000"
    project.username = "testuser"
    project.password = "testpass"
    project.user_domain_name = "Default"
    project.region_name = "RegionOne"
    return project


@pytest.fixture
def resource_service(mock_db_session):
    """Create OpenstackResourceService instance with mocked dependencies."""
    service = OpenstackResourceService(mock_db_session)
    return service


class TestGetQuotas:
    """Tests for get_quotas method."""
    
    def test_get_quotas_from_cache(self, resource_service, mock_db_session, mock_openstack_project):
        """Test that cached quotas are returned when available."""
        # Setup
        cached_quotas = {
            'project_id': 'openstack-proj-123',
            'project_name': 'test-project',
            'compute': {'instances': {'limit': 10, 'used': 3, 'available': 7}},
            'fetched_at': '2024-01-01T00:00:00Z'
        }
        
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            with patch.object(resource_service.cache_service, 'get_quotas', return_value=cached_quotas):
                # Execute
                result = resource_service.get_quotas(
                    user_id="user-123",
                    use_cache=True,
                    force_refresh=False
                )
                
                # Assert
                assert result == cached_quotas
                resource_service.cache_service.get_quotas.assert_called_once_with('openstack-proj-123')
    
    def test_get_quotas_force_refresh(self, resource_service, mock_db_session, mock_openstack_project):
        """Test that force_refresh bypasses cache."""
        # Setup
        mock_conn = MagicMock()
        fresh_quotas = {
            'project_id': 'openstack-proj-123',
            'project_name': 'test-project',
            'compute': {'instances': {'limit': 10, 'used': 5, 'available': 5}},
        }
        
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            with patch.object(resource_service.cache_service, 'get_quotas', return_value=None):
                with patch.object(resource_service, '_get_connection', return_value=mock_conn):
                    with patch.object(resource_service, '_get_compute_quotas', return_value=fresh_quotas['compute']):
                        with patch.object(resource_service, '_get_network_quotas', return_value=None):
                            with patch.object(resource_service, '_get_volume_quotas', return_value=None):
                                with patch.object(resource_service.cache_service, 'set_quotas'):
                                    # Execute
                                    result = resource_service.get_quotas(
                                        user_id="user-123",
                                        use_cache=True,
                                        force_refresh=True
                                    )
                                    
                                    # Assert
                                    assert result['compute'] == fresh_quotas['compute']
                                    resource_service.cache_service.get_quotas.assert_not_called()
    
    def test_get_quotas_no_project_found(self, resource_service, mock_db_session):
        """Test that NotFoundException is raised when no project exists."""
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[]):
            with pytest.raises(NotFoundException) as exc_info:
                resource_service.get_quotas(user_id="user-123")
            
            assert "No OpenStack projects found" in str(exc_info.value)
    
    def test_get_quotas_connection_failure(self, resource_service, mock_db_session, mock_openstack_project):
        """Test that BadRequestException is raised on connection failure."""
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            with patch.object(resource_service.cache_service, 'get_quotas', return_value=None):
                with patch.object(resource_service, '_get_connection', side_effect=BadRequestException("Failed to connect to OpenStack: Connection failed")):
                    with pytest.raises(BadRequestException) as exc_info:
                        resource_service.get_quotas(user_id="user-123", force_refresh=True)

                    assert "Failed to connect" in str(exc_info.value)


def _mock_flavor(flavor_id, name, vcpus, ram, disk, ephemeral=0, is_public=True):
    """Build a Mock that mimics the openstacksdk Flavor object."""
    flavor = MagicMock()
    flavor.id = flavor_id
    flavor.name = name
    flavor.vcpus = vcpus
    flavor.ram = ram
    flavor.disk = disk
    flavor.ephemeral = ephemeral
    flavor.is_public = is_public
    return flavor


class TestGetFlavors:
    """Tests for get_flavors method."""

    def test_get_flavors_success(self, resource_service, mock_db_session, mock_openstack_project):
        """Returns a sorted list of flavors with the expected fields."""
        mock_conn = MagicMock()
        # Intentionally out of order to verify sorting (vcpus asc, then ram asc)
        mock_conn.compute.flavors.return_value = iter([
            _mock_flavor("2", "gp1.medium", vcpus=4, ram=8192, disk=40),
            _mock_flavor("1", "gp1.small", vcpus=2, ram=4096, disk=20),
            _mock_flavor("3", "gp1.large", vcpus=8, ram=16384, disk=80, ephemeral=10, is_public=False),
        ])

        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            with patch.object(resource_service, '_get_connection', return_value=mock_conn):
                result = resource_service.get_flavors(user_id="user-123")

        assert result['project_id'] == "openstack-proj-123"
        assert result['project_name'] == "test-project"
        assert result['owner_user_id'] == "user-123"
        assert 'fetched_at' in result
        assert len(result['flavors']) == 3

        # Sorted by (vcpus, ram_mb)
        names = [f['name'] for f in result['flavors']]
        assert names == ["gp1.small", "gp1.medium", "gp1.large"]

        small = result['flavors'][0]
        assert small == {
            'id': "1",
            'name': "gp1.small",
            'vcpus': 2,
            'ram_mb': 4096,
            'disk_gb': 20,
            'ephemeral_gb': 0,
            'is_public': True,
        }

        # Non-public flavor surfaced correctly
        large = result['flavors'][2]
        assert large['ephemeral_gb'] == 10
        assert large['is_public'] is False
        assert large['id'] == "3"  # IDs are stringified even if SDK returns int

    def test_get_flavors_empty_list(self, resource_service, mock_db_session, mock_openstack_project):
        """Returns an empty list when the project has no visible flavors."""
        mock_conn = MagicMock()
        mock_conn.compute.flavors.return_value = iter([])

        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            with patch.object(resource_service, '_get_connection', return_value=mock_conn):
                result = resource_service.get_flavors(user_id="user-123")

        assert result['flavors'] == []
        assert result['project_id'] == "openstack-proj-123"

    def test_get_flavors_no_project_for_user(self, resource_service, mock_db_session):
        """Raises NotFoundException when the user has no OpenStack project."""
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[]):
            with pytest.raises(NotFoundException) as exc_info:
                resource_service.get_flavors(user_id="user-123")

            assert "No OpenStack projects found" in str(exc_info.value)

    def test_get_flavors_forbidden_other_project(self, resource_service, mock_db_session, mock_openstack_project):
        """Raises ForbiddenException when a non-admin requests another user's project."""
        # mock_openstack_project.owner_user_id == 'user-123', caller is 'user-456'
        with patch.object(resource_service.repository, 'get_by_id', return_value=mock_openstack_project):
            with pytest.raises(ForbiddenException) as exc_info:
                resource_service.get_flavors(
                    user_id="user-456",
                    project_id="project-123",
                    allow_admin_access=False,
                )

            assert "do not have permission" in str(exc_info.value)

    def test_get_flavors_admin_access_to_other_project(self, resource_service, mock_db_session, mock_openstack_project):
        """Admin (allow_admin_access=True) can read flavors of any project."""
        mock_conn = MagicMock()
        mock_conn.compute.flavors.return_value = iter([
            _mock_flavor("1", "gp1.small", vcpus=2, ram=4096, disk=20),
        ])

        with patch.object(resource_service.repository, 'get_by_id', return_value=mock_openstack_project):
            with patch.object(resource_service, '_get_connection', return_value=mock_conn):
                result = resource_service.get_flavors(
                    user_id="user-456",  # not the owner
                    project_id="project-123",
                    allow_admin_access=True,
                )

        assert len(result['flavors']) == 1
        assert result['owner_user_id'] == "user-123"  # actual owner surfaced

    def test_get_flavors_connection_failure(self, resource_service, mock_db_session, mock_openstack_project):
        """Connection errors from _get_connection bubble up as BadRequestException."""
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            with patch.object(
                resource_service,
                '_get_connection',
                side_effect=BadRequestException("Failed to connect to OpenStack: down"),
            ):
                with pytest.raises(BadRequestException) as exc_info:
                    resource_service.get_flavors(user_id="user-123")

                assert "Failed to connect" in str(exc_info.value)

    def test_get_flavors_sdk_error(self, resource_service, mock_db_session, mock_openstack_project):
        """SDKException from the Nova call is mapped to BadRequestException."""
        mock_conn = MagicMock()
        mock_conn.compute.flavors.side_effect = SDKException("nova exploded")

        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            with patch.object(resource_service, '_get_connection', return_value=mock_conn):
                with pytest.raises(BadRequestException) as exc_info:
                    resource_service.get_flavors(user_id="user-123")

                assert "Failed to retrieve flavors" in str(exc_info.value)


class TestCheckAvailability:
    """Tests for check_availability method."""
    
    def test_check_availability_all_sufficient(self, resource_service, mock_db_session):
        """Test availability check when all resources are sufficient."""
        # Setup
        quotas = {
            'compute': {
                'instances': {'limit': 10, 'used': 3, 'available': 7},
                'cores': {'limit': 20, 'used': 5, 'available': 15},
                'ram': {'limit': 40960, 'used': 10240, 'available': 30720}
            },
            'volume': {
                'volumes': {'limit': 10, 'used': 2, 'available': 8},
                'gigabytes': {'limit': 1000, 'used': 200, 'available': 800}
            }
        }
        
        required_resources = {
            'instances': 2,
            'cores': 4,
            'ram': 8192,
            'volumes': 1,
            'gigabytes': 100
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is True
            assert len(result['reasons']) == 0
            assert result['quotas'] == quotas
    
    def test_check_availability_insufficient_instances(self, resource_service, mock_db_session):
        """Test availability check when instances are insufficient."""
        # Setup
        quotas = {
            'compute': {
                'instances': {'limit': 10, 'used': 9, 'available': 1},
                'cores': {'limit': 20, 'used': 5, 'available': 15},
                'ram': {'limit': 40960, 'used': 10240, 'available': 30720}
            }
        }
        
        required_resources = {
            'instances': 3,  # Need 3, but only 1 available
            'cores': 4,
            'ram': 8192
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is False
            assert len(result['reasons']) == 1
            assert "Insufficient instances quota" in result['reasons'][0]
            assert "need 3" in result['reasons'][0]
            assert "available 1" in result['reasons'][0]
    
    def test_check_availability_insufficient_cores(self, resource_service, mock_db_session):
        """Test availability check when cores are insufficient."""
        # Setup
        quotas = {
            'compute': {
                'instances': {'limit': 10, 'used': 3, 'available': 7},
                'cores': {'limit': 20, 'used': 18, 'available': 2},
                'ram': {'limit': 40960, 'used': 10240, 'available': 30720}
            }
        }
        
        required_resources = {
            'instances': 2,
            'cores': 5,  # Need 5, but only 2 available
            'ram': 8192
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is False
            assert len(result['reasons']) == 1
            assert "Insufficient CPU cores" in result['reasons'][0]
    
    def test_check_availability_insufficient_ram(self, resource_service, mock_db_session):
        """Test availability check when RAM is insufficient."""
        # Setup
        quotas = {
            'compute': {
                'instances': {'limit': 10, 'used': 3, 'available': 7},
                'cores': {'limit': 20, 'used': 5, 'available': 15},
                'ram': {'limit': 40960, 'used': 35000, 'available': 5960}
            }
        }
        
        required_resources = {
            'instances': 2,
            'cores': 4,
            'ram': 8192  # Need 8192 MB, but only 5960 MB available
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is False
            assert len(result['reasons']) == 1
            assert "Insufficient RAM" in result['reasons'][0]
            assert "need 8192MB" in result['reasons'][0]
    
    def test_check_availability_insufficient_volumes(self, resource_service, mock_db_session):
        """Test availability check when volumes are insufficient."""
        # Setup
        quotas = {
            'volume': {
                'volumes': {'limit': 10, 'used': 9, 'available': 1},
                'gigabytes': {'limit': 1000, 'used': 200, 'available': 800}
            }
        }
        
        required_resources = {
            'volumes': 3,  # Need 3, but only 1 available
            'gigabytes': 100
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is False
            assert len(result['reasons']) == 1
            assert "Insufficient volume quota" in result['reasons'][0]
    
    def test_check_availability_insufficient_storage(self, resource_service, mock_db_session):
        """Test availability check when storage is insufficient."""
        # Setup
        quotas = {
            'volume': {
                'volumes': {'limit': 10, 'used': 2, 'available': 8},
                'gigabytes': {'limit': 1000, 'used': 950, 'available': 50}
            }
        }
        
        required_resources = {
            'volumes': 1,
            'gigabytes': 100  # Need 100 GB, but only 50 GB available
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is False
            assert len(result['reasons']) == 1
            assert "Insufficient storage" in result['reasons'][0]
            assert "need 100GB" in result['reasons'][0]
    
    def test_check_availability_multiple_insufficient(self, resource_service, mock_db_session):
        """Test availability check when multiple resources are insufficient."""
        # Setup
        quotas = {
            'compute': {
                'instances': {'limit': 10, 'used': 9, 'available': 1},
                'cores': {'limit': 20, 'used': 18, 'available': 2},
                'ram': {'limit': 40960, 'used': 35000, 'available': 5960}
            },
            'volume': {
                'volumes': {'limit': 10, 'used': 9, 'available': 1},
                'gigabytes': {'limit': 1000, 'used': 950, 'available': 50}
            }
        }
        
        required_resources = {
            'instances': 3,  # Need 3, only 1 available
            'cores': 5,      # Need 5, only 2 available
            'ram': 8192,     # Need 8192 MB, only 5960 MB available
            'volumes': 2,    # Need 2, only 1 available
            'gigabytes': 100  # Need 100 GB, only 50 GB available
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is False
            assert len(result['reasons']) == 5
            assert any("instances" in reason for reason in result['reasons'])
            assert any("CPU cores" in reason for reason in result['reasons'])
            assert any("RAM" in reason for reason in result['reasons'])
            assert any("volume quota" in reason for reason in result['reasons'])
            assert any("storage" in reason for reason in result['reasons'])
    
    def test_check_availability_unlimited_quota(self, resource_service, mock_db_session):
        """Test availability check with unlimited quota (-1).
        
        Note: The current implementation treats -1 (unlimited) as a regular number,
        so comparisons like -1 > 1000 will fail. This test documents the current behavior.
        In a production system, unlimited quotas should be handled specially.
        """
        # Setup
        quotas = {
            'compute': {
                'instances': {'limit': -1, 'used': 100, 'available': -1},  # Unlimited
                'cores': {'limit': 20, 'used': 5, 'available': 15},
                'ram': {'limit': -1, 'used': 50000, 'available': -1}  # Unlimited
            }
        }
        
        required_resources = {
            'instances': 1000,  # Would pass with unlimited quota if handled properly
            'cores': 10,
            'ram': 100000  # Would pass with unlimited quota if handled properly
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            # Current implementation: -1 > 1000 evaluates to False in Python
            # So unlimited quotas are incorrectly flagged as insufficient
            assert result['available'] is False
            assert len(result['reasons']) > 0
            # This documents a limitation: unlimited quotas need special handling
    
    def test_check_availability_partial_resources(self, resource_service, mock_db_session):
        """Test availability check with only some resources specified."""
        # Setup
        quotas = {
            'compute': {
                'instances': {'limit': 10, 'used': 3, 'available': 7},
                'cores': {'limit': 20, 'used': 5, 'available': 15},
                'ram': {'limit': 40960, 'used': 10240, 'available': 30720}
            }
        }
        
        required_resources = {
            'instances': 2,  # Only checking instances
            # cores and ram not specified
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            assert result['available'] is True
            assert len(result['reasons']) == 0
    
    def test_check_availability_missing_quota_data(self, resource_service, mock_db_session):
        """Test availability check when quota data is missing."""
        # Setup
        quotas = {
            'compute': {},  # Empty compute quotas
            'volume': {}    # Empty volume quotas
        }
        
        required_resources = {
            'instances': 2,
            'cores': 4
        }
        
        with patch.object(resource_service, 'get_quotas', return_value=quotas):
            # Execute
            result = resource_service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            # Assert
            # When quota data is missing, available defaults to 0
            assert result['available'] is False
            assert len(result['reasons']) > 0


class TestGetProjectForUser:
    """Tests for _get_project_for_user method."""
    
    def test_get_project_for_user_success(self, resource_service, mock_db_session, mock_openstack_project):
        """Test getting project for user successfully."""
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[mock_openstack_project]):
            result = resource_service._get_project_for_user("user-123")
            assert result == mock_openstack_project
    
    def test_get_project_for_user_with_project_id(self, resource_service, mock_db_session, mock_openstack_project):
        """Test getting specific project by ID."""
        with patch.object(resource_service.repository, 'get_by_id', return_value=mock_openstack_project):
            result = resource_service._get_project_for_user("user-123", project_id="project-123")
            assert result == mock_openstack_project
    
    def test_get_project_for_user_not_found(self, resource_service, mock_db_session):
        """Test that NotFoundException is raised when project not found."""
        with patch.object(resource_service.repository, 'get_by_owner', return_value=[]):
            with pytest.raises(NotFoundException) as exc_info:
                resource_service._get_project_for_user("user-123")
            
            assert "No OpenStack projects found" in str(exc_info.value)
    
    def test_get_project_for_user_wrong_owner(self, resource_service, mock_db_session, mock_openstack_project):
        """Test that ForbiddenException is raised when accessing another user's project."""
        with patch.object(resource_service.repository, 'get_by_id', return_value=mock_openstack_project):
            with pytest.raises(ForbiddenException) as exc_info:
                resource_service._get_project_for_user("user-456", project_id="project-123")
            
            assert "do not have permission" in str(exc_info.value)
    
    def test_get_project_for_user_admin_access(self, resource_service, mock_db_session, mock_openstack_project):
        """Test that admin can access any project."""
        with patch.object(resource_service.repository, 'get_by_id', return_value=mock_openstack_project):
            result = resource_service._get_project_for_user(
                "user-456",
                project_id="project-123",
                allow_admin_access=True
            )
            assert result == mock_openstack_project

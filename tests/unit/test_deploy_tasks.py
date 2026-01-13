"""Unit tests for deployment tasks."""
from unittest.mock import MagicMock, patch
from src.tasks.deploy_tasks import deploy_stack, _build_stack_parameters, _get_heat_template_placeholder
from src.models.deployment import DeploymentStatus


class TestDeployTasks:
    """Test suite for Celery deployment tasks."""
    
    def test_build_stack_parameters_with_config(self):
        """Test building stack parameters from deployment config."""
        mock_deployment = MagicMock()
        mock_deployment.id = "test-deployment-123"
        mock_deployment.config_json = '{"flavor": "m1.large", "image": "Ubuntu-24.04"}'
        
        params = _build_stack_parameters(mock_deployment)
        
        assert params["vm_name"] == "vm-test-dep"
        assert params["flavor"] == "m1.large"
        assert params["image"] == "Ubuntu-24.04"
    
    def test_build_stack_parameters_without_config(self):
        """Test building stack parameters without custom config."""
        mock_deployment = MagicMock()
        mock_deployment.id = "test-deployment-456"
        mock_deployment.config_json = None
        
        params = _build_stack_parameters(mock_deployment)
        
        assert params["vm_name"] == "vm-test-dep"
        assert len(params) == 1
    
    def test_get_heat_template_placeholder(self):
        """Test placeholder Heat template generation."""
        template = _get_heat_template_placeholder("Ubuntu Server")
        
        assert template["heat_template_version"] == "2021-04-16"
        assert "Ubuntu Server" in template["description"]
        assert "parameters" in template
        assert "resources" in template
        assert "vm_instance" in template["resources"]
    
    @patch("src.tasks.deploy_tasks._get_openstack_connection")
    @patch("src.tasks.deploy_tasks._create_heat_stack")
    @patch("src.tasks.deploy_tasks._wait_for_stack_completion")
    @patch("src.tasks.deploy_tasks._handle_stack_completion")
    @patch("src.tasks.deploy_tasks.SessionLocal")
    def test_deploy_stack_success(
        self,
        mock_session_local,
        mock_handle_completion,
        mock_wait,
        mock_create_stack,
        mock_get_conn
    ):
        """Test successful stack deployment."""
        # Setup mocks
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        mock_deployment = MagicMock()
        mock_deployment.id = "test-deployment-789"
        mock_deployment.openstack_stack_id = None
        mock_deployment.config_json = None
        
        mock_template_version = MagicMock()
        mock_template_version.template.name = "Test Template"
        mock_deployment.template_version = mock_template_version
        
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = mock_deployment
        mock_repo.get_with_template.return_value = mock_deployment
        
        mock_stack = MagicMock()
        mock_stack.id = "stack-123"
        mock_create_stack.return_value = mock_stack
        
        mock_wait.return_value = "CREATE_COMPLETE"
        
        with patch("src.tasks.deploy_tasks.DeploymentRepository", return_value=mock_repo):
            # Execute task by calling the underlying function directly
            result = deploy_stack.run("test-deployment-789")
        
        # Verify
        assert result["status"] == "completed"
        assert result["deployment_id"] == "test-deployment-789"
        assert result["stack_id"] == "stack-123"
        mock_repo.update_status.assert_called_with("test-deployment-789", DeploymentStatus.CREATING)
        mock_repo.update_stack_id.assert_called_with("test-deployment-789", "stack-123")
        mock_handle_completion.assert_called_once()
    
    @patch("src.tasks.deploy_tasks.SessionLocal")
    def test_deploy_stack_deployment_not_found(self, mock_session_local):
        """Test deployment task when deployment doesn't exist."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = None
        
        with patch("src.tasks.deploy_tasks.DeploymentRepository", return_value=mock_repo):
            result = deploy_stack.run("nonexistent-deployment")
        
        assert result["status"] == "failed"
        assert "not found" in result["error"]
    
    @patch("src.tasks.deploy_tasks._check_existing_stack")
    @patch("src.tasks.deploy_tasks._handle_stack_completion")
    @patch("src.tasks.deploy_tasks.SessionLocal")
    def test_deploy_stack_idempotency(
        self,
        mock_session_local,
        mock_handle_completion,
        mock_check_stack
    ):
        """Test idempotency - skip creation if stack already exists."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        mock_deployment = MagicMock()
        mock_deployment.id = "test-deployment-999"
        mock_deployment.openstack_stack_id = "existing-stack-123"
        
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = mock_deployment
        
        mock_check_stack.return_value = "CREATE_COMPLETE"
        
        with patch("src.tasks.deploy_tasks.DeploymentRepository", return_value=mock_repo):
            result = deploy_stack.run("test-deployment-999")
        
        assert result["status"] == "completed"
        assert result["stack_id"] == "existing-stack-123"
        mock_check_stack.assert_called_once_with("existing-stack-123")
        mock_handle_completion.assert_called_once()

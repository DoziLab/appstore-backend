"""Tests for template parameter extraction from app.yaml."""
import pytest
from unittest.mock import Mock
from sqlalchemy.orm import Session

from src.services.template_version_file_service import TemplateVersionFileService
from src.models.template_version_file import TemplateVersionFile, FileType
from src.core.exceptions import NotFoundException, BadRequestException
from src.schemas.template_parameters import TemplateParametersResponse


@pytest.fixture
def mock_db():
    """Mock database session."""
    return Mock(spec=Session)


@pytest.fixture
def service(mock_db):
    """Create TemplateVersionFileService instance."""
    return TemplateVersionFileService(mock_db)


@pytest.fixture
def valid_app_yaml_content():
    """Valid app.yaml content with parameters."""
    return """
id: postgres-group-db
name: PostgreSQL Group Database
version: 1.0.0
description: "Provisioniert pro Gruppe eine Ubuntu-VM mit PostgreSQL."

parameters:
  instance_name:
    type: string
    required: true
    description: "Eindeutiger Name der Instanz/Stacks (z.B. kursX-grp1-db)."

  image:
    type: string
    required: true
    default: "Ubuntu 22.04 2025-01"
    description: "OpenStack Image Name/ID."

  flavor:
    type: string
    required: true
    default: "gp1.small"
    description: "OpenStack Flavor."

  network:
    type: string
    required: true
    default: "NAT"
    description: "Internes Tenant-Netzwerk."

  group_login:
    type: string
    required: true
    description: "Linux Username für Gruppen-Zugang (SSH)."

  db_password:
    type: string
    required: true
    description: "Passwort für den PostgreSQL User."

  postgres_version:
    type: int
    required: false
    default: 14
    description: "PostgreSQL Major-Version."
"""


@pytest.fixture
def mock_app_yaml_file(valid_app_yaml_content):
    """Mock app.yaml file."""
    return TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content=valid_app_yaml_content,
        file_size=len(valid_app_yaml_content),
        is_primary=False,
        order=0
    )


def test_get_template_parameters_success(service, mock_app_yaml_file):
    """Test successful parameter extraction from app.yaml."""
    service.file_repo.get_by_version_id = Mock(return_value=[mock_app_yaml_file])
    
    result = service.get_template_parameters("version-123", skip_access_check=True)
    
    assert isinstance(result, TemplateParametersResponse)
    assert result.template_version_id == "version-123"
    assert len(result.parameters) == 7
    
    # Check required parameter
    instance_name = next(p for p in result.parameters if p.name == "instance_name")
    assert instance_name.type == "string"
    assert instance_name.required is True
    assert instance_name.default is None
    assert "Eindeutiger Name" in instance_name.description
    
    # Check parameter with default
    flavor = next(p for p in result.parameters if p.name == "flavor")
    assert flavor.type == "string"
    assert flavor.required is True
    assert flavor.default == "gp1.small"
    
    # Check optional parameter
    postgres_version = next(p for p in result.parameters if p.name == "postgres_version")
    assert postgres_version.type == "int"
    assert postgres_version.required is False
    assert postgres_version.default == 14


def test_get_template_parameters_no_app_yaml(service):
    """Test error when app.yaml file is not found."""
    other_file = TemplateVersionFile(
        id="file-456",
        template_version_id="version-123",
        file_name="template.yaml",
        file_type=FileType.HEAT_TEMPLATE,
        file_path="heat/template.yaml",
        content="heat_template_version: 2018-08-31",
        file_size=100,
        is_primary=True,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[other_file])
    
    with pytest.raises(NotFoundException) as exc_info:
        service.get_template_parameters("version-123", skip_access_check=True)
    
    assert "app.yaml file not found" in str(exc_info.value)


def test_get_template_parameters_empty_content(service):
    """Test error when app.yaml has no content."""
    empty_file = TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content=None,
        file_size=0,
        is_primary=False,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[empty_file])
    
    with pytest.raises(BadRequestException) as exc_info:
        service.get_template_parameters("version-123", skip_access_check=True)
    
    assert "has no content" in str(exc_info.value)


def test_get_template_parameters_invalid_yaml(service):
    """Test error when app.yaml contains invalid YAML."""
    invalid_file = TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content="invalid: yaml: content: [unclosed",
        file_size=100,
        is_primary=False,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[invalid_file])
    
    with pytest.raises(BadRequestException) as exc_info:
        service.get_template_parameters("version-123", skip_access_check=True)
    
    assert "Invalid YAML" in str(exc_info.value)


def test_get_template_parameters_not_dict(service):
    """Test error when app.yaml is not a dictionary."""
    invalid_file = TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content="just a string",
        file_size=100,
        is_primary=False,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[invalid_file])
    
    with pytest.raises(BadRequestException) as exc_info:
        service.get_template_parameters("version-123", skip_access_check=True)
    
    assert "must contain a YAML dictionary" in str(exc_info.value)


def test_get_template_parameters_missing_parameters_section(service):
    """Test error when app.yaml is missing parameters section."""
    no_params_file = TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content="id: test\nname: Test Template\nversion: 1.0.0",
        file_size=100,
        is_primary=False,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[no_params_file])
    
    with pytest.raises(BadRequestException) as exc_info:
        service.get_template_parameters("version-123", skip_access_check=True)
    
    assert "missing 'parameters' section" in str(exc_info.value)


def test_get_template_parameters_parameters_not_dict(service):
    """Test error when parameters section is not a dictionary."""
    invalid_params_file = TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content="id: test\nparameters: ['list', 'instead', 'of', 'dict']",
        file_size=100,
        is_primary=False,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[invalid_params_file])
    
    with pytest.raises(BadRequestException) as exc_info:
        service.get_template_parameters("version-123", skip_access_check=True)
    
    assert "must be a dictionary" in str(exc_info.value)


def test_get_template_parameters_skips_invalid_param_definitions(service):
    """Test that invalid parameter definitions are skipped with warning."""
    mixed_file = TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content="""
id: test
parameters:
  valid_param:
    type: string
    required: true
    description: "Valid parameter"
  invalid_param: "just a string, not a dict"
  another_valid:
    type: int
    required: false
    default: 10
    description: "Another valid param"
""",
        file_size=100,
        is_primary=False,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[mixed_file])
    
    result = service.get_template_parameters("version-123", skip_access_check=True)
    
    # Should have 2 valid parameters, invalid one skipped
    assert len(result.parameters) == 2
    param_names = [p.name for p in result.parameters]
    assert "valid_param" in param_names
    assert "another_valid" in param_names
    assert "invalid_param" not in param_names


def test_get_template_parameters_default_values(service):
    """Test that parameters use correct default values when fields are missing."""
    minimal_file = TemplateVersionFile(
        id="file-123",
        template_version_id="version-123",
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content="""
id: test
parameters:
  minimal_param:
    # Only name is provided, all others should use defaults
    description: "Test"
""",
        file_size=100,
        is_primary=False,
        order=0
    )
    service.file_repo.get_by_version_id = Mock(return_value=[minimal_file])
    
    result = service.get_template_parameters("version-123", skip_access_check=True)
    
    assert len(result.parameters) == 1
    param = result.parameters[0]
    assert param.name == "minimal_param"
    assert param.type == "string"  # Default
    assert param.required is False  # Default
    assert param.default is None  # Default
    assert param.description == "Test"

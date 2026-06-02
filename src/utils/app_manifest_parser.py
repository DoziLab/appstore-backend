"""Parser for app.yaml manifest files."""
import yaml
from typing import Optional, Any


class AppManifestParameter:
    """Represents a parameter from app.yaml."""
    
    def __init__(
        self,
        name: str,
        type: str,
        default: Any = None,
        required: bool = False,
        secret: bool = False,
        label: Optional[str] = None,
        description: Optional[str] = None,
        step: Optional[str] = None,
        enum: Optional[list] = None,
        hidden: bool = False
    ):
        self.name = name
        self.type = type
        self.default = default
        self.required = required
        self.secret = secret
        self.label = label
        self.description = description
        self.step = step
        self.enum = enum
        self.hidden = hidden
    
    def to_dict(self) -> dict:
        """Convert parameter to dictionary."""
        result = {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "required": self.required,
            "secret": self.secret,
            "label": self.label,
            "description": self.description
        }
        
        # Add optional fields only if they are set
        if self.step is not None:
            result["step"] = self.step
        if self.enum is not None:
            result["enum"] = self.enum
        if self.hidden:
            result["hidden"] = self.hidden
        
        return result


class AppManifestParser:
    """Parser for app.yaml manifest files."""
    
    @staticmethod
    def parse(content: str) -> dict:
        """Parse app.yaml content and extract metadata.
        
        Args:
            content: Raw YAML content of app.yaml
            
        Returns:
            Dictionary containing parsed app metadata including parameters
            
        Raises:
            yaml.YAMLError: If YAML parsing fails
            ValueError: If required fields are missing
        """
        try:
            data = yaml.safe_load(content)
            
            if not data:
                raise ValueError("Empty YAML content")
            
            # Extract app metadata
            app_info = data.get("app", {})
            
            # Extract parameters
            parameters = []
            params_list = data.get("parameters", [])
            
            for param in params_list:
                if not isinstance(param, dict):
                    continue
                    
                name = param.get("name")
                if not name:
                    continue
                
                parameter = AppManifestParameter(
                    name=name,
                    type=param.get("type", "string"),
                    default=param.get("default"),
                    required=param.get("required", False),
                    secret=param.get("secret", False),
                    label=param.get("label"),
                    description=param.get("description"),
                    step=param.get("step"),
                    enum=param.get("enum"),
                    hidden=param.get("hidden", False)
                )
                parameters.append(parameter.to_dict())
            
            # Extract outputs
            outputs = []
            outputs_list = data.get("outputs", [])
            
            for output in outputs_list:
                if not isinstance(output, dict):
                    continue
                    
                name = output.get("name")
                if not name:
                    continue
                
                outputs.append({
                    "name": name,
                    "from_heat_output": output.get("from_heat_output"),
                    "description": output.get("description")
                })
            
            # Extract artifacts
            artifacts = data.get("artifacts", {})
            
            return {
                "app": {
                    "name": app_info.get("name"),
                    "label": app_info.get("label"),
                    "version": app_info.get("version"),
                    "description": app_info.get("description"),
                    "owner_team": app_info.get("owner_team")
                },
                "artifacts": artifacts,
                "parameters": parameters,
                "outputs": outputs
            }
            
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML: {e}")
    
    @staticmethod
    def extract_parameters(content: str) -> list[dict]:
        """Extract only parameters from app.yaml content.

        Args:
            content: Raw YAML content of app.yaml

        Returns:
            List of parameter dictionaries
        """
        try:
            parsed = AppManifestParser.parse(content)
            return parsed.get("parameters", [])
        except Exception:
            return []

    # Mapping from artifacts: keys in app.yaml to TemplateVersionFile.FileType values.
    # Order in this dict is also the deployment execution order suggested in the README.
    ARTIFACT_KEY_TO_FILE_TYPE: dict[str, str] = {
        "heat_template": "HEAT_TEMPLATE",
        "cloud_init": "CLOUD_INIT",
        "ansible_playbook": "ANSIBLE_PLAYBOOK",
        "ansible": "ANSIBLE_PLAYBOOK",
        "helm_chart": "HELM_CHART",
        "helm": "HELM_CHART",
        "shell_script": "SHELL_SCRIPT",
        "config_file": "CONFIG_FILE",
    }

    PRIMARY_ARTIFACT_KEY: str = "heat_template"

    @staticmethod
    def get_linked_files(parsed: dict) -> list[dict]:
        """Convert the artifacts dict from a parsed app.yaml into an ordered list
        of file descriptors that the GitHub-import service can fetch.

        Each entry contains:
          - artifact_key: original key in artifacts (e.g. "heat_template")
          - file_type:    FileType enum value (string, e.g. "HEAT_TEMPLATE")
          - relative_path: path relative to the directory containing app.yaml
          - is_primary:   True for the heat_template artifact (deployment entrypoint)
          - order:        position from artifacts dict (insertion order)

        The ordering is preserved from the YAML so that deployment runs files in
        the order their authors specified - matching the user-supplied app.yaml
        contract.
        """
        artifacts = parsed.get("artifacts") if isinstance(parsed, dict) else None
        if not isinstance(artifacts, dict):
            return []

        result: list[dict] = []
        for index, (key, value) in enumerate(artifacts.items()):
            if not isinstance(value, str) or not value.strip():
                continue
            file_type = AppManifestParser.ARTIFACT_KEY_TO_FILE_TYPE.get(key, "OTHER")
            result.append({
                "artifact_key": key,
                "file_type": file_type,
                "relative_path": value.strip(),
                "is_primary": key == AppManifestParser.PRIMARY_ARTIFACT_KEY,
                "order": index + 1,
            })
        return result

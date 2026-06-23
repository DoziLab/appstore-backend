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
        result = {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "required": self.required,
            "secret": self.secret,
            "label": self.label,
            "description": self.description,
        }
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
        """Parse app.yaml and return all sections.

        Returns a dict with keys:
          app, parameters, outputs, credentials, user_files
        """
        try:
            data = yaml.safe_load(content)
            if not data:
                raise ValueError("Empty YAML content")

            app_info = data.get("app", {})

            # Parameters
            parameters = []
            for param in data.get("parameters", []):
                if not isinstance(param, dict) or not param.get("name"):
                    continue
                parameters.append(AppManifestParameter(
                    name=param["name"],
                    type=param.get("type", "string"),
                    default=param.get("default"),
                    required=param.get("required", False),
                    secret=param.get("secret", False),
                    label=param.get("label"),
                    description=param.get("description"),
                    step=param.get("step"),
                    enum=param.get("enum"),
                    hidden=param.get("hidden", False),
                ).to_dict())

            # Outputs
            outputs = []
            for output in data.get("outputs", []):
                if not isinstance(output, dict) or not output.get("name"):
                    continue
                outputs.append({
                    "name": output["name"],
                    "label": output.get("label"),
                    "from_heat_output": output.get("from_heat_output"),
                    "description": output.get("description"),
                })

            # Credentials
            credentials_raw = data.get("credentials") or {}
            credentials = {
                "per_group": credentials_raw.get("per_group") or [],
                "teacher": credentials_raw.get("teacher") or [],
            }

            # User files
            user_files = data.get("user_files") or []

            # Artifacts (preserve YAML insertion order — used by GitHub import to
            # type and order linked files; see get_linked_files()).
            artifacts_raw = data.get("artifacts") or {}
            artifacts = artifacts_raw if isinstance(artifacts_raw, dict) else {}

            return {
                "app": {
                    "name": app_info.get("name"),
                    "label": app_info.get("label"),
                    "version": app_info.get("version"),
                    "description": app_info.get("description"),
                    "owner_team": app_info.get("owner_team"),
                    "allow_user_files": app_info.get("allow_user_files", False),
                },
                "parameters": parameters,
                "outputs": outputs,
                "credentials": credentials,
                "user_files": user_files,
                "artifacts": artifacts,
            }

        except Exception as e:
            raise ValueError(f"Failed to parse app.yaml: {e}")

    @staticmethod
    def extract_parameters(content: str) -> list[dict]:
        """Extract only parameters from app.yaml content.

        Args:
            content: Raw YAML content of app.yaml

        Returns:
            List of parameter dictionaries
        """
        try:
            return AppManifestParser.parse(content).get("parameters", [])
        except Exception:
            return []

    @staticmethod
    def extract_credentials(content: str) -> dict:
        """Return the credentials block or empty structure on failure."""
        try:
            return AppManifestParser.parse(content).get("credentials", {"per_group": [], "teacher": []})
        except Exception:
            return {"per_group": [], "teacher": []}

    @staticmethod
    def extract_user_files(content: str) -> list[dict]:
        """Return the user_files list or empty list on failure."""
        try:
            return AppManifestParser.parse(content).get("user_files", [])
        except Exception:
            return []

    # Mapping from artifacts: keys in app.yaml to TemplateVersionFile.FileType values.
    # Order in this dict is also the deployment execution order suggested in the README.
    #
    # Some keys come in two flavours:
    #   - singular (``shell_script: scripts/x.sh``)         → exactly one path
    #   - plural   (``shell_scripts: [a.sh, b.sh]``)        → a list of paths
    # Both expand to the same FileType. The plural form is for templates that
    # have multiple files of the same kind (e.g. several helper scripts in
    # ``scripts/`` or several config files in ``files/``) — without it, every
    # extra file would be imported as OTHER and silently skipped at deploy
    # time because the Ansible-copy step only picks up SHELL_SCRIPT/CONFIG_FILE.
    ARTIFACT_KEY_TO_FILE_TYPE: dict[str, str] = {
        "heat_template": "HEAT_TEMPLATE",
        "cloud_init": "CLOUD_INIT",
        "ansible_playbook": "ANSIBLE_PLAYBOOK",
        "ansible": "ANSIBLE_PLAYBOOK",
        "helm_chart": "HELM_CHART",
        "helm": "HELM_CHART",
        "shell_script": "SHELL_SCRIPT",
        "shell_scripts": "SHELL_SCRIPT",   # list-of-paths variant
        "config_file": "CONFIG_FILE",
        "config_files": "CONFIG_FILE",     # list-of-paths variant
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
          - order:        monotonically increasing across all paths (1-based)

        Values may be either a single string (``heat_template: heat/main.yaml``)
        or a list of strings (``shell_scripts: [a.sh, b.sh]``) — a list expands
        to multiple entries, one per path. Both single- and plural-key forms
        share the same FileType (see ARTIFACT_KEY_TO_FILE_TYPE).

        Non-string / non-list values (dict, None, etc.) and blank strings are
        skipped silently so that a malformed entry doesn't kill the whole
        import.

        The ordering is preserved from the YAML so that deployment runs files in
        the order their authors specified - matching the user-supplied app.yaml
        contract.
        """
        artifacts = parsed.get("artifacts") if isinstance(parsed, dict) else None
        if not isinstance(artifacts, dict):
            return []

        result: list[dict] = []
        order = 0
        for key, value in artifacts.items():
            # Normalise both single-string and list-of-strings into one path list.
            # Anything else (dict, None, ...) → no paths → no entries.
            if isinstance(value, str):
                paths = [value.strip()] if value.strip() else []
            elif isinstance(value, list):
                paths = [v.strip() for v in value if isinstance(v, str) and v.strip()]
            else:
                paths = []

            file_type = AppManifestParser.ARTIFACT_KEY_TO_FILE_TYPE.get(key, "OTHER")
            for path in paths:
                order += 1
                result.append({
                    "artifact_key": key,
                    "file_type": file_type,
                    # ``is_primary`` is reserved for the singular heat_template
                    # key. A list-of-paths variant could never produce a primary
                    # anyway because PRIMARY_ARTIFACT_KEY is exactly that string.
                    "relative_path": path,
                    "is_primary": key == AppManifestParser.PRIMARY_ARTIFACT_KEY,
                    "order": order,
                })
        return result

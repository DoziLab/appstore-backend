"""Unit tests for AppManifestParser.get_linked_files().

Used by GithubImportService to map artifacts: declarations into FileType /
is_primary / order hints when storing files imported from GitHub.
"""
from src.utils.app_manifest_parser import AppManifestParser


class TestGetLinkedFiles:
    """get_linked_files() - artifact dict -> ordered list of file descriptors."""

    def test_returns_empty_list_when_artifacts_missing(self):
        assert AppManifestParser.get_linked_files({"app": {}}) == []

    def test_returns_empty_list_when_artifacts_not_dict(self):
        assert AppManifestParser.get_linked_files({"artifacts": "string-not-dict"}) == []
        assert AppManifestParser.get_linked_files({"artifacts": []}) == []

    def test_returns_empty_list_for_non_dict_input(self):
        assert AppManifestParser.get_linked_files(None) == []
        assert AppManifestParser.get_linked_files("not-a-dict") == []

    def test_preserves_yaml_declaration_order(self):
        parsed = {
            "artifacts": {
                "heat_template": "heat/main.yaml",
                "cloud_init": "cloud-init/init.yaml",
                "ansible_playbook": "ansible/play.yml",
            }
        }
        result = AppManifestParser.get_linked_files(parsed)

        assert [e["artifact_key"] for e in result] == [
            "heat_template", "cloud_init", "ansible_playbook"
        ]
        assert [e["order"] for e in result] == [1, 2, 3]

    def test_maps_known_artifact_keys_to_file_types(self):
        parsed = {
            "artifacts": {
                "heat_template": "h.yaml",
                "cloud_init": "c.yaml",
                "ansible_playbook": "a.yml",
                "helm_chart": "chart/",
                "shell_script": "run.sh",
                "config_file": "cfg.toml",
            }
        }
        by_key = {e["artifact_key"]: e["file_type"] for e in AppManifestParser.get_linked_files(parsed)}

        assert by_key["heat_template"] == "HEAT_TEMPLATE"
        assert by_key["cloud_init"] == "CLOUD_INIT"
        assert by_key["ansible_playbook"] == "ANSIBLE_PLAYBOOK"
        assert by_key["helm_chart"] == "HELM_CHART"
        assert by_key["shell_script"] == "SHELL_SCRIPT"
        assert by_key["config_file"] == "CONFIG_FILE"

    def test_unknown_artifact_key_falls_back_to_other(self):
        parsed = {"artifacts": {"my_custom_artifact": "weird.yaml"}}
        result = AppManifestParser.get_linked_files(parsed)
        assert result[0]["file_type"] == "OTHER"

    def test_only_heat_template_is_primary(self):
        parsed = {
            "artifacts": {
                "heat_template": "h.yaml",
                "cloud_init": "c.yaml",
                "ansible_playbook": "a.yml",
            }
        }
        result = AppManifestParser.get_linked_files(parsed)
        primaries = {e["artifact_key"]: e["is_primary"] for e in result}
        assert primaries == {
            "heat_template": True,
            "cloud_init": False,
            "ansible_playbook": False,
        }

    def test_no_primary_when_heat_template_missing(self):
        parsed = {"artifacts": {"cloud_init": "c.yaml", "shell_script": "s.sh"}}
        result = AppManifestParser.get_linked_files(parsed)
        assert all(not e["is_primary"] for e in result)

    def test_relative_path_is_trimmed(self):
        parsed = {"artifacts": {"heat_template": "  heat/main.yaml  "}}
        result = AppManifestParser.get_linked_files(parsed)
        assert result[0]["relative_path"] == "heat/main.yaml"

    def test_skips_entries_with_non_string_or_blank_values(self):
        parsed = {
            "artifacts": {
                "heat_template": "heat/main.yaml",
                "broken_dict": {"path": "nope.yaml"},
                "broken_blank": "   ",
                "broken_none": None,
                "cloud_init": "cloud-init/init.yaml",
            }
        }
        result = AppManifestParser.get_linked_files(parsed)
        kept = [e["artifact_key"] for e in result]
        assert kept == ["heat_template", "cloud_init"]

    def test_aliases_map_to_same_file_type(self):
        # `ansible` and `ansible_playbook` should both map to ANSIBLE_PLAYBOOK
        # `helm` and `helm_chart` should both map to HELM_CHART
        parsed = {"artifacts": {"ansible": "play.yml", "helm": "chart/"}}
        result = AppManifestParser.get_linked_files(parsed)
        by_key = {e["artifact_key"]: e["file_type"] for e in result}
        assert by_key["ansible"] == "ANSIBLE_PLAYBOOK"
        assert by_key["helm"] == "HELM_CHART"

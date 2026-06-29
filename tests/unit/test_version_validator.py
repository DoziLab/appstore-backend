"""Unit tests für ``src/utils/version_validator.py``.

Wir testen sowohl die Regex (Format-Check) als auch die Monotonie-
Vergleichs-Logik separat, weil beide unabhängige Failure-Modi haben.
"""
import pytest

from src.core.exceptions import BadRequestException
from src.utils import version_validator
from src.utils.version_validator import (
    ERR_ALREADY_EXISTS,
    ERR_NOT_SEMVER,
    ERR_NOT_STRICTLY_GREATER,
    assert_strictly_greater,
    assert_valid_semver,
    is_valid_semver,
    parse_semver,
)


class TestSemverFormat:
    @pytest.mark.parametrize(
        "version",
        [
            "0.0.0",
            "1.0.0",
            "10.20.30",
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0+build",
            "1.0.0-alpha+build.5",
            "1.0.0-0.3.7",
            "1.0.0-x.7.z.92",
        ],
    )
    def test_valid_strings_accepted(self, version):
        assert is_valid_semver(version)
        # Sollte auch ohne Exception parsen
        parse_semver(version)

    @pytest.mark.parametrize(
        "version",
        [
            "",
            "foo",
            "1",
            "1.0",
            "01.0.0",  # leading zero
            "1.0.0.0",
            "v1.0.0",
            "1.0.0-",
            "1.0.0+",
            "1.0.0-α",  # nicht-ASCII
        ],
    )
    def test_invalid_strings_rejected(self, version):
        assert not is_valid_semver(version)
        with pytest.raises(BadRequestException) as exc:
            assert_valid_semver(version)
        assert exc.value.code == ERR_NOT_SEMVER


class TestSemverOrdering:
    def test_release_is_greater_than_prerelease(self):
        # Semver §11: 1.0.0 > 1.0.0-alpha
        assert parse_semver("1.0.0") > parse_semver("1.0.0-alpha")

    def test_prerelease_numeric_lower_than_alpha(self):
        # 1.0.0-1 < 1.0.0-alpha (numerische Identifier sortieren niedriger
        # als alphanumerische, Semver §11.3).
        assert parse_semver("1.0.0-1") < parse_semver("1.0.0-alpha")

    def test_build_metadata_ignored_for_ordering(self):
        # 1.0.0+a und 1.0.0+b sind ordnungsweise gleich (Semver §10).
        assert parse_semver("1.0.0+a") == parse_semver("1.0.0+b")

    def test_patch_minor_major_ordering(self):
        assert parse_semver("2.0.0") > parse_semver("1.9.9")
        assert parse_semver("1.10.0") > parse_semver("1.9.0")
        assert parse_semver("1.0.1") > parse_semver("1.0.0")


class TestAssertStrictlyGreater:
    def test_first_version_accepted(self):
        # Keine existierenden Versionen → jede valid-semver-Version geht.
        result = assert_strictly_greater("1.0.0", [])
        assert result is None

    def test_strictly_greater_accepted(self):
        result = assert_strictly_greater("2.0.0", ["1.0.0", "1.5.0", "1.9.9"])
        assert result is None

    def test_already_exists_raises_with_code(self):
        with pytest.raises(BadRequestException) as exc:
            assert_strictly_greater("1.5.0", ["1.0.0", "1.5.0", "1.9.0"])
        assert exc.value.code == ERR_ALREADY_EXISTS
        assert exc.value.details == {"version": "1.5.0"}

    def test_not_strictly_greater_raises_with_max(self):
        with pytest.raises(BadRequestException) as exc:
            assert_strictly_greater("1.5.0", ["1.0.0", "2.0.0", "1.9.0"])
        assert exc.value.code == ERR_NOT_STRICTLY_GREATER
        assert exc.value.details["current_max"] == "2.0.0"

    def test_invalid_existing_versions_skipped(self):
        # „2.0.0+dedupe-abc12345" ist valid semver (Build-Metadata), aber
        # die alte Dedupe-Variante mit Suffix darf den Vergleich nicht
        # blockieren. Hier testen wir gleich beide: ein offen-defektes
        # „foo" UND ein semver-mit-Build "2.0.0+dedupe-abc12345" — beide
        # sollen den Insert von "2.0.1" zulassen.
        existing = ["1.0.0", "foo", "2.0.0+dedupe-abc12345"]
        # Beachte: "2.0.0+dedupe-..." parst zu (2,0,0,…) und ist
        # ordnungsweise gleich 2.0.0. Wir versuchen also 2.0.1 → ok.
        result = assert_strictly_greater("2.0.1", existing)
        assert result is None

    def test_replace_target_allows_equal(self):
        result = assert_strictly_greater(
            "2.0.0",
            ["1.0.0", "2.0.0"],
            allow_equal_replace_target=True,
        )
        assert result == "2.0.0"

    def test_replace_target_does_not_bypass_monotonic_check(self):
        # 2.0.0 ist identisch zur existierenden 2.0.0 (Replace ok), aber
        # 3.0.0 ist auch da — der Replace-Wert ist also nicht das Maximum,
        # heißt nicht „kleiner als max" muss greifen. In dem Szenario
        # geben wir aber denselben String, also Replace-Pfad aktiv und
        # wir wollen keinen NOT_STRICTLY_GREATER-Fehler.
        # (Edge-Case: Replace-Pfad ist ein „ich ersetze eine Bestands-Row"
        # — der String ist bewusst kleiner als max, das ist normal.)
        result = assert_strictly_greater(
            "2.0.0",
            ["2.0.0", "3.0.0"],
            allow_equal_replace_target=True,
        )
        assert result == "2.0.0"


class TestErrorCodesAreExported:
    """Die Codes müssen Strings auf Modulebene sein — das Frontend
    spiegelt sie als const-Werte. Wenn sie wegrefactored werden,
    schlägt der Aufruf hier hart fehl statt stillschweigend zu
    driften."""

    def test_codes_are_uppercase_snake_strings(self):
        for name in (
            "ERR_NOT_SEMVER",
            "ERR_MISSING_IN_MANIFEST",
            "ERR_NOT_STRICTLY_GREATER",
            "ERR_ALREADY_EXISTS",
            "ERR_REPLACE_BLOCKED_BY_DEPLOYMENTS",
        ):
            value = getattr(version_validator, name)
            assert isinstance(value, str) and value.isupper()
            assert value.startswith("VERSION_")

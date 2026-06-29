"""Semver validation and ordering for template-version strings.

Background
----------
Vor dieser Datei hat das Backend an mehreren Stellen unkontrolliert
Versions-Strings übernommen (aus `app.version` in app.yaml, aus manuellem
Create-Body) ohne Format-Check oder Eindeutigkeit pro Template. Dadurch
landeten z.B. mehrere Versionen mit `version="2.0.0"` parallel im selben
Template (nur `(template_id, commit_sha)` war unique).

Diese Helper-Funktionen sind die einzige zentrale Stelle, an der wir
Versions-Strings gegen Semver-2.0 prüfen und in eine vergleichbare Form
bringen. Aufrufer sind:
- ``GithubImportService`` (importiert Versionsnummer aus `app.yaml`)
- ``TemplateVersionService.create_version`` / ``create_version_with_files``
  / ``update_version`` (Versionsnummer aus Request)

Auf DB-Ebene gibt es zusätzlich einen ``UniqueConstraint`` auf
``(template_id, version)`` (Migration ``ebc91d7b5d43``); diese Helper sind
der user-friendly Vor-Check, damit die Antwort nicht „IntegrityError" lautet.
"""
import re
from typing import Iterable

from src.core.exceptions import BadRequestException


# Semver 2.0.0 — `MAJOR.MINOR.PATCH(-PRERELEASE)?(+BUILD)?`. Keine
# führenden Nullen in den Zahlen, Identifier in Prerelease/Build sind
# ASCII-alnum + Punkt + Bindestrich. Sehr nah an der offiziellen Referenz-
# Regex, aber zur Lesbarkeit ungroupt; wir validieren hier nur das Format,
# das Sortieren übernimmt ``parse_semver``.
SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)"
    r"\.(?P<minor>0|[1-9]\d*)"
    r"\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


# Strukturierte Fehler-Codes für das Frontend-Branching.
# Konvention: ``BadRequestException(message=…, code=…, details={…})`` —
# Handler in src/core/exceptions.py reicht beide ins API-`errors`-Feld weiter.
ERR_NOT_SEMVER = "VERSION_NOT_SEMVER"
ERR_MISSING_IN_MANIFEST = "VERSION_MISSING_IN_MANIFEST"
ERR_NOT_STRICTLY_GREATER = "VERSION_NOT_STRICTLY_GREATER"
ERR_ALREADY_EXISTS = "VERSION_ALREADY_EXISTS"
ERR_REPLACE_BLOCKED_BY_DEPLOYMENTS = "VERSION_REPLACE_BLOCKED_BY_DEPLOYMENTS"


def _parse_prerelease_key(prerelease: str | None) -> tuple:
    """Build a comparable key for the prerelease portion per semver §11.

    Semver-Sortierung:
    - Eine fehlende Prerelease ist *größer* als eine vorhandene (1.0.0 > 1.0.0-alpha).
      Wir kodieren das als ``(1,)`` für „kein prerelease, sortiert oben" und
      ``(0, …identifier…)`` für „mit prerelease, sortiert unten".
    - Numerische Identifier vergleichen numerisch, alphanumerische lexikalisch;
      numerische Identifier sind „kleiner" als alphanumerische bei gleicher Position.
    """
    if prerelease is None:
        return (1,)  # ranks higher than any (0, …) prerelease key
    parts = []
    for ident in prerelease.split("."):
        if ident.isdigit():
            # (0, numeric_value) sortiert unter (1, alphanum_value)
            parts.append((0, int(ident)))
        else:
            parts.append((1, ident))
    return (0, tuple(parts))


def parse_semver(version: str) -> tuple:
    """Return a comparable tuple representation of a semver string.

    Build-Metadata (alles nach ``+``) wird laut Semver-Spezifikation NICHT
    in den Vergleich einbezogen — ``1.0.0+a`` == ``1.0.0+b`` ordnungsweise.
    Aufrufer, die Eindeutigkeit auf String-Ebene wollen, müssen das selbst
    prüfen (DB-Constraint übernimmt das).

    Wirft ``ValueError``, wenn der String kein Semver ist. Aufrufer nutzen
    typischerweise ``is_valid_semver`` zur Vorab-Prüfung.
    """
    m = SEMVER_RE.match(version)
    if not m:
        raise ValueError(f"Not a valid semver: {version!r}")
    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch"))
    pre_key = _parse_prerelease_key(m.group("prerelease"))
    return (major, minor, patch, pre_key)


def is_valid_semver(version: str) -> bool:
    """Pure boolean check — used by Pydantic validators that already have
    their own raising path. The raising assert_* below is for service code."""
    return bool(version) and SEMVER_RE.match(version) is not None


def assert_valid_semver(version: str) -> None:
    """Raise ``BadRequestException(ERR_NOT_SEMVER)`` if invalid.

    Klar formulierte Fehlermeldung mit Beispiel — die meisten Owner kommen
    aus „mein App-Store-Repo hatte vorher keine Versionsnummer-Disziplin"
    und wissen nicht intuitiv, was Semver verlangt.
    """
    if not is_valid_semver(version):
        raise BadRequestException(
            f"Versionsnummer '{version}' ist kein gültiges Semver. "
            f"Format: MAJOR.MINOR.PATCH, z. B. '1.0.0' oder '2.0.1-beta'.",
            code=ERR_NOT_SEMVER,
            details={"version": version},
        )


def assert_strictly_greater(
    new_version: str,
    existing_versions: Iterable[str],
    *,
    allow_equal_replace_target: bool = False,
) -> str | None:
    """Stell sicher, dass ``new_version`` strikt größer ist als jede existierende.

    Wirft entweder:
    - ``ERR_NOT_STRICTLY_GREATER`` wenn eine existierende Version >= ist
      und der String nicht identisch zu ihr ist.
    - ``ERR_ALREADY_EXISTS`` wenn der String identisch zu einer existierenden
      ist und ``allow_equal_replace_target`` nicht gesetzt ist. Frontend
      branchst darauf und bietet den Replace-Pfad an.

    Gibt den String der existierenden „Kollisions-Version" zurück, wenn
    ``allow_equal_replace_target=True`` und eine Kollision vorliegt — sonst
    None (kein Konflikt). Aufrufer im Replace-Pfad nutzen den Rückgabewert
    nicht direkt (sie haben die Row schon), aber er ist konsistent mit der
    Erwartung „diese Funktion sagt mir, was kollidiert".

    Nicht-semver-Strings unter den existierenden werden defensiv
    übersprungen — sie können nur über Legacy-Daten/Dedupe-Suffixe
    entstehen und sollen keinen neuen Insert blockieren.
    """
    # Vorab-Check: new_version muss valid sein. assert_valid_semver hebt sonst.
    assert_valid_semver(new_version)
    new_key = parse_semver(new_version)

    # Existierende Strings, die nicht Semver sind (z.B. „2.0.0+dedupe-abc"
    # nach der Dedupe-Migration), als Block-Vergleich überspringen — sie
    # zählen weder zur Monotonie-Vergleichsmenge noch zur Identitäts-Kollision.
    max_existing: tuple | None = None
    max_existing_str: str | None = None
    identical: str | None = None
    for ev in existing_versions:
        if ev == new_version:
            identical = ev
            continue
        try:
            ev_key = parse_semver(ev)
        except ValueError:
            continue
        if max_existing is None or ev_key > max_existing:
            max_existing = ev_key
            max_existing_str = ev

    if identical is not None and not allow_equal_replace_target:
        raise BadRequestException(
            f"Version '{new_version}' ist in diesem Template bereits vorhanden. "
            f"Bitte bumpe `app.version` im Repo oder ersetze die bestehende Version.",
            code=ERR_ALREADY_EXISTS,
            details={"version": new_version},
        )

    # Replace-Pfad: wir ersetzen eine bestehende Version mit demselben String.
    # In dem Fall bewusst KEIN Monotonie-Check — der String ist absichtlich
    # gleich (kleiner-oder-gleich Max ist normal); der Caller hat die
    # existierende Row schon zur Löschung markiert.
    if identical is not None and allow_equal_replace_target:
        return identical

    if max_existing is not None and new_key <= max_existing:
        raise BadRequestException(
            f"Version '{new_version}' ist nicht strikt größer als die bestehende "
            f"höchste Version '{max_existing_str}'. Bitte bumpe `app.version` im Repo.",
            code=ERR_NOT_STRICTLY_GREATER,
            details={"version": new_version, "current_max": max_existing_str},
        )

    return identical

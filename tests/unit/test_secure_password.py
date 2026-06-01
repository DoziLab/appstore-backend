"""Tests for the memorable password generator."""
import re

from src.utils.secure_password import generate_memorable_password


def test_generated_password_format():
    pw = generate_memorable_password("Grp1")
    # Default min_length=12 may add extra noun tokens, so the format is
    # "Grp1" followed by one or more "-word" tokens, ending in "-NN".
    assert re.match(r"^Grp1(-[a-z]+)+-\d{2}$", pw), pw


def test_generated_password_uses_prefix_verbatim():
    pw = generate_memorable_password("TeacherDb")
    assert pw.startswith("TeacherDb-")


def test_generated_passwords_are_random_enough():
    """Same prefix should produce mostly distinct outputs across many calls."""
    seen = {generate_memorable_password("Grp1") for _ in range(100)}
    # 50 * 50 * 100 = 250k combinations, so 100 draws should virtually never collide.
    assert len(seen) >= 95, f"only {len(seen)} unique values in 100 draws"


def test_generated_passwords_differ_for_different_prefixes():
    a = generate_memorable_password("Grp1")
    b = generate_memorable_password("Grp2")
    assert a != b
    assert a.startswith("Grp1-")
    assert b.startswith("Grp2-")


def test_min_length_is_respected_for_strict_pwquality_policies():
    """When the deployment configures pw_min_length=30, every generated password
    must be at least 30 characters — otherwise cloud-init's chpasswd will reject
    them and the user accounts will never be created."""
    for _ in range(100):
        pw = generate_memorable_password("Grp1", min_length=30)
        assert len(pw) >= 30, f"got {len(pw)}-char password: {pw!r}"


def test_default_min_length_still_satisfies_default_policy():
    """The Heat default pw_min_length is 12, so default-call output must be >= 12."""
    for _ in range(100):
        pw = generate_memorable_password("Grp1")
        assert len(pw) >= 12, f"got {len(pw)}-char password: {pw!r}"


def test_min_length_extension_keeps_numeric_suffix_at_end():
    """Sanity check: even after extension with extra noun tokens, the trailing
    2-digit number stays at the end (so the format remains visually consistent)."""
    pw = generate_memorable_password("Grp1", min_length=40)
    assert re.match(r"^Grp1(-[a-z]+){2,}-\d{2}$", pw), pw


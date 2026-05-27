"""Tests for the memorable password generator."""
import re

from src.utils.secure_password import generate_memorable_password


def test_generated_password_format():
    pw = generate_memorable_password("Grp1")
    assert re.match(r"^Grp1-[a-z]+-[a-z]+-\d{2}$", pw), pw


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

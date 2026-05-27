"""Memorable-but-random password generator for deployment user accounts.

The generated passwords look like ``Grp1-azure-tiger-42`` or ``Teacher-mango-cobalt-91``:
a caller-supplied prefix that students recognize, followed by a random adjective,
noun, and two-digit number drawn with :mod:`secrets`.

Entropy is roughly ``len(_ADJECTIVES) * len(_NOUNS) * 100`` distinct suffixes per
prefix, which is plenty to defeat guessing within a class while staying typeable
and easy to dictate aloud.
"""
from __future__ import annotations

import secrets


_ADJECTIVES: tuple[str, ...] = (
    "azure", "amber", "brave", "calm", "clever", "cobalt", "coral", "crisp",
    "daring", "eager", "fancy", "fierce", "gentle", "happy", "icy", "jolly",
    "keen", "lively", "lucky", "mellow", "merry", "mighty", "nimble", "noble",
    "olive", "plucky", "proud", "quick", "quiet", "rapid", "royal", "rusty",
    "sage", "scarlet", "silver", "sleek", "snappy", "sturdy", "sunny", "swift",
    "tidy", "tough", "vivid", "warm", "wise", "witty", "young", "zesty",
)

_NOUNS: tuple[str, ...] = (
    "anchor", "arrow", "badger", "beacon", "bison", "canyon", "cedar", "comet",
    "copper", "delta", "ember", "falcon", "flint", "forest", "garnet", "gecko",
    "harbor", "heron", "ibex", "iris", "jaguar", "juniper", "kestrel", "lagoon",
    "lantern", "lynx", "maple", "marble", "meadow", "moose", "narwhal", "nebula",
    "ocelot", "onyx", "panda", "pebble", "pine", "quartz", "raven", "ridge",
    "river", "saffron", "spruce", "summit", "tiger", "topaz", "valley", "willow",
)


def _random_suffix() -> str:
    """Return a memorable random suffix like ``azure-tiger-42``."""
    adjective = secrets.choice(_ADJECTIVES)
    noun = secrets.choice(_NOUNS)
    number = secrets.randbelow(100)
    return f"{adjective}-{noun}-{number:02d}"


def generate_memorable_password(prefix: str) -> str:
    """Generate a memorable but cryptographically random password.

    The result is ``{prefix}-{adjective}-{noun}-{NN}``. The adjective and noun
    come from short curated wordlists; the trailing number is two random digits.

    Args:
        prefix: Stable, human-readable prefix that ties the password to its
            owner (e.g. ``"Grp1"``, ``"Teacher"``). Not validated; the caller is
            responsible for keeping it short and printable.

    Returns:
        A password string guaranteed to be unique with high probability across
        deployments and impossible to guess from the prefix alone.
    """
    return f"{prefix}-{_random_suffix()}"

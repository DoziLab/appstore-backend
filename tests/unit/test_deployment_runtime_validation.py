"""Tests for runtime_months validation on DeploymentCreate / DeploymentExtend."""
import pytest
from pydantic import ValidationError

from src.schemas.deployment import (
    ALLOWED_RUNTIME_MONTHS,
    DEFAULT_RUNTIME_MONTHS,
    DeploymentExtend,
)


def test_default_runtime_months_is_4():
    """Wizard default == backend default == 4 months."""
    assert DEFAULT_RUNTIME_MONTHS == 4


def test_allowed_set_matches_wizard_dropdown():
    """Backend's allowed set must match the Wizard <Select> options exactly."""
    assert set(ALLOWED_RUNTIME_MONTHS) == {1, 3, 4, 6, 12, 24, 36}


@pytest.mark.parametrize("months", [1, 3, 4, 6, 12, 24, 36])
def test_extend_accepts_each_allowed_runtime(months: int):
    """Every dropdown option must validate."""
    extend = DeploymentExtend(runtime_months=months)
    assert extend.runtime_months == months


@pytest.mark.parametrize("bad", [0, -1, 2, 5, 7, 18, 48, 100])
def test_extend_rejects_disallowed_runtime(bad: int):
    """Anything outside the wizard's offered set must fail validation."""
    with pytest.raises(ValidationError):
        DeploymentExtend(runtime_months=bad)


def test_extend_default_is_4_when_omitted():
    """Empty body extends by the default 4 months."""
    extend = DeploymentExtend()
    assert extend.runtime_months == DEFAULT_RUNTIME_MONTHS

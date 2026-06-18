"""Unit tests for the HMAC-signed OAuth state token util."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.core.exceptions import BadRequestException
from src.utils.oauth_state import sign_state, verify_state


class TestSignVerifyRoundTrip:
    def test_round_trip_returns_user_id(self):
        token = sign_state("user-123")
        assert verify_state(token) == "user-123"

    def test_each_signing_uses_a_fresh_nonce(self):
        a = sign_state("user-123")
        b = sign_state("user-123")
        assert a != b  # different nonce embedded


class TestVerifyState:
    def test_rejects_empty_token(self):
        with pytest.raises(BadRequestException, match="format"):
            verify_state("")

    def test_rejects_token_without_separator(self):
        with pytest.raises(BadRequestException, match="format"):
            verify_state("noseparatorhere")

    def test_rejects_token_with_too_many_separators(self):
        with pytest.raises(BadRequestException, match="format"):
            verify_state("a.b.c")

    def test_rejects_tampered_payload(self):
        token = sign_state("user-123")
        payload, sig = token.split(".", 1)
        tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
        with pytest.raises(BadRequestException, match="signature mismatch"):
            verify_state(f"{tampered}.{sig}")

    def test_rejects_tampered_signature(self):
        token = sign_state("user-123")
        payload, sig = token.split(".", 1)
        bad_sig = "A" + sig[1:] if sig[0] != "A" else "B" + sig[1:]
        with pytest.raises(BadRequestException, match="signature mismatch"):
            verify_state(f"{payload}.{bad_sig}")

    def test_rejects_expired_token(self):
        # Sign with TTL=1s, then jump time forward
        token = sign_state("user-123", ttl_seconds=1)
        with patch("src.utils.oauth_state.time.time", return_value=time.time() + 10):
            with pytest.raises(BadRequestException, match="expired"):
                verify_state(token)

    def test_rejects_malformed_signature_b64(self):
        token = sign_state("user-123")
        payload, _ = token.split(".", 1)
        with pytest.raises(BadRequestException):
            verify_state(f"{payload}.!!!not_base64!!!")

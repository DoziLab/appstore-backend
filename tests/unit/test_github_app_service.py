"""Unit tests for GithubAppService — JWT minting + installation token cache."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

from src.core.exceptions import BadRequestException
from src.services import github_app_service as gha_module
from src.services.github_app_service import GithubAppService


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    """Generate an ephemeral RSA keypair to sign + verify the App JWT."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


@pytest.fixture(autouse=True)
def _clear_cache():
    """Class-level cache leaks between tests; reset before each."""
    GithubAppService._cache.clear()
    yield
    GithubAppService._cache.clear()


class TestMintAppJwt:
    def test_mint_app_jwt_signs_with_rs256_and_sets_iss(self, rsa_keypair):
        private_pem, public_pem = rsa_keypair
        service = GithubAppService(app_id=12345, private_key_pem=private_pem)

        token = service.mint_app_jwt()
        decoded = jose_jwt.decode(
            token, public_pem, algorithms=["RS256"], options={"verify_aud": False}
        )

        assert decoded["iss"] == 12345
        # iat should be slightly in the past (clock-skew tolerance)
        assert decoded["iat"] <= decoded["exp"]
        # exp should be at most ~10 minutes in the future
        assert (decoded["exp"] - decoded["iat"]) <= 11 * 60

    def test_mint_app_jwt_raises_when_unconfigured(self):
        service = GithubAppService(app_id=None, private_key_pem=None)
        with pytest.raises(BadRequestException, match="not configured"):
            service.mint_app_jwt()


class TestGetInstallationToken:
    def _make_service(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        return GithubAppService(app_id=12345, private_key_pem=private_pem)

    def _http_response(self, status_code: int, body: dict | None = None, text: str = ""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = body or {}
        resp.text = text
        return resp

    def _client_returning(self, response):
        client = MagicMock()
        client.post.return_value = response
        client.delete.return_value = response
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        return client

    def test_mints_and_caches_installation_token(self, rsa_keypair):
        service = self._make_service(rsa_keypair)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        )
        client = self._client_returning(
            self._http_response(201, {"token": "ghs_abc", "expires_at": future})
        )
        with patch.object(gha_module.httpx, "Client", return_value=client):
            token1 = service.get_installation_token(78901234)
            token2 = service.get_installation_token(78901234)
        assert token1 == "ghs_abc"
        assert token2 == "ghs_abc"
        # Second call hit the cache, not GitHub
        assert client.post.call_count == 1

    def test_refreshes_when_token_near_expiry(self, rsa_keypair):
        service = self._make_service(rsa_keypair)
        # Pre-load cache with a token that expires in 60 seconds (< 5 min leeway)
        from src.services.github_app_service import _CachedToken

        soon = datetime.now(timezone.utc) + timedelta(seconds=60)
        GithubAppService._cache[78901234] = _CachedToken(token="stale", expires_at=soon)

        fresh_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        )
        client = self._client_returning(
            self._http_response(201, {"token": "ghs_fresh", "expires_at": fresh_expiry})
        )
        with patch.object(gha_module.httpx, "Client", return_value=client):
            token = service.get_installation_token(78901234)
        assert token == "ghs_fresh"
        assert client.post.call_count == 1

    def test_404_signals_missing_installation(self, rsa_keypair):
        service = self._make_service(rsa_keypair)
        client = self._client_returning(self._http_response(404, {"message": "no"}))
        with patch.object(gha_module.httpx, "Client", return_value=client):
            with pytest.raises(BadRequestException, match="not found"):
                service.get_installation_token(78901234)

    def test_other_errors_raise_generic_message(self, rsa_keypair):
        service = self._make_service(rsa_keypair)
        client = self._client_returning(self._http_response(500, text="boom"))
        with patch.object(gha_module.httpx, "Client", return_value=client):
            with pytest.raises(BadRequestException, match="Could not authenticate"):
                service.get_installation_token(78901234)


class TestRevokeInstallation:
    def _client_returning(self, status_code: int):
        resp = MagicMock()
        resp.status_code = status_code
        client = MagicMock()
        client.delete.return_value = resp
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        return client

    def test_revoke_204_returns_true_and_evicts_cache(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        service = GithubAppService(app_id=12345, private_key_pem=private_pem)
        from src.services.github_app_service import _CachedToken

        GithubAppService._cache[42] = _CachedToken(
            token="x", expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        with patch.object(gha_module.httpx, "Client", return_value=self._client_returning(204)):
            assert service.revoke_installation(42) is True
        assert 42 not in GithubAppService._cache

    def test_revoke_returns_false_on_error_status(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        service = GithubAppService(app_id=12345, private_key_pem=private_pem)
        with patch.object(gha_module.httpx, "Client", return_value=self._client_returning(500)):
            assert service.revoke_installation(42) is False

    def test_revoke_returns_false_when_app_unconfigured(self):
        service = GithubAppService(app_id=None, private_key_pem=None)
        assert service.revoke_installation(42) is False

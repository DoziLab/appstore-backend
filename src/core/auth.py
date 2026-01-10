"""JWT authentication utilities."""
from datetime import datetime, timezone
from typing import Optional
from jose import JWTError, jwt
from fastapi import HTTPException, status
from src.core.config import get_settings


settings = get_settings()


class JWTPayload:
    """Structured JWT payload data."""
    
    def __init__(
        self,
        sub: str,
        email: str,
        name: str,
        role: str,
        exp: Optional[int] = None,
        iat: Optional[int] = None,
        iss: Optional[str] = None,
        aud: Optional[str] = None,
    ):
        self.sub = sub  # external_id (subject)
        self.email = email
        self.name = name
        self.role = role
        self.exp = exp  # expiration timestamp
        self.iat = iat  # issued at timestamp
        self.iss = iss  # issuer
        self.aud = aud  # audience


def decode_jwt_token(token: str) -> JWTPayload:
    """Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        JWTPayload with user information
        
    Raises:
        HTTPException: If token is invalid, expired, or missing required claims
    """
    try:
        # Decode and validate token
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
            }
        )
        
        # Validate required claims
        required_claims = ["sub", "email", "name", "role"]
        missing_claims = [claim for claim in required_claims if claim not in payload]
        if missing_claims:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token missing required claims: {', '.join(missing_claims)}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Check expiration manually for better error message
        if "exp" in payload:
            exp_timestamp = payload["exp"]
            if datetime.fromtimestamp(exp_timestamp, tz=timezone.utc) < datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        
        return JWTPayload(
            sub=payload["sub"],
            email=payload["email"],
            name=payload["name"],
            role=payload["role"],
            exp=payload.get("exp"),
            iat=payload.get("iat"),
            iss=payload.get("iss"),
            aud=payload.get("aud"),
        )
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

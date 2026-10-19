"""Gatekeeper's own access tokens (Step 7).

After login, the browser gets a short-lived RS256 JWT that we sign ourselves.
Every protected request presents it as `Authorization: Bearer <token>`.
The token looks the same whichever IdP the user logged in through.
"""

import base64
import hashlib
import json
import time
import uuid
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import db
from app.auth.bridge import Principal
from app.config import settings

ALGORITHM = "RS256"

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _keys():
    """Load the private key once and derive its public JWK and key ID."""
    private_key = serialization.load_pem_private_key(base64.b64decode(settings.token_signing_key_b64), password=None)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    # Key ID = RFC 7638 thumbprint, so it changes automatically when the key does.
    thumbprint_input = json.dumps({k: public_jwk[k] for k in ("e", "kty", "n")}, separators=(",", ":"), sort_keys=True)
    kid = base64.urlsafe_b64encode(hashlib.sha256(thumbprint_input.encode()).digest()).rstrip(b"=").decode()
    public_jwk.update(kid=kid, alg=ALGORITHM, use="sig")
    return private_key, public_jwk


def jwks() -> dict:
    return {"keys": [_keys()[1]]}


def issue_access_token(principal: Principal) -> str:
    private_key, public_jwk = _keys()
    now = int(time.time())
    claims = {
        "iss": settings.token_issuer,
        "aud": settings.token_audience,
        "sub": principal.user_id,
        "tenant_id": principal.tenant_id,
        "role": principal.role,
        "scope": " ".join(principal.scopes),
        "iat": now,
        "exp": now + settings.token_ttl_seconds,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, private_key, algorithm=ALGORITHM, headers={"kid": public_jwk["kid"]})


def _unauthorized(detail: str) -> HTTPException:
    # 401 = "I don't know who you are."
    return HTTPException(401, detail, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})


def verify_access_token(token: str) -> dict:
    private_key, public_jwk = _keys()
    try:
        if jwt.get_unverified_header(token).get("kid") != public_jwk["kid"]:
            raise _unauthorized("Token was not signed by this server's current key")
        return jwt.decode(
            token,
            private_key.public_key(),
            algorithms=[ALGORITHM],
            audience=settings.token_audience,
            issuer=settings.token_issuer,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "tenant_id", "role", "scope"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")


def require_scope(scope: str):
    """FastAPI dependency: a valid token for an active user that carries `scope`."""

    async def dependency(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
        if creds is None:
            raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        claims = verify_access_token(creds.credentials)

        # Check the database on EVERY request. A valid signature only proves the
        # token was true 15 minutes ago; this catches deactivation immediately.
        async with db.get_pool().acquire() as conn:
            user = await conn.fetchrow(
                "SELECT email, role, active FROM users WHERE id = $1::uuid AND tenant_id = $2::uuid",
                claims["sub"], claims["tenant_id"],
            )
        if user is None or not user["active"]:
            raise _unauthorized("User is not active")
        if user["role"] != claims["role"]:
            # Role changed since login (e.g. demoted). Make them log in again.
            raise _unauthorized("Role changed; log in again")

        scopes = tuple(claims["scope"].split())
        if scope not in scopes:
            # 403 = "I know who you are, and the answer is no."
            raise HTTPException(403, f"Missing scope {scope}",
                                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'})
        return Principal(
            user_id=claims["sub"], tenant_id=claims["tenant_id"], email=user["email"],
            role=claims["role"], scopes=scopes,
        )

    return dependency


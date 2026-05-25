"""Bearer-token auth for the daemon.

Jupyter pattern: a single shared token in ``~/.sopify/config.yaml``;
every ``/api/v1/**`` request needs ``Authorization: Bearer <token>``.

Token comparison is constant-time so a leaked timing side-channel can't
recover the secret. Token is loaded once at daemon startup and stored
on ``request.app.state`` to avoid reading the config file on every
request.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status


async def verify_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency — raises 401 if the bearer token is missing or wrong.

    Acceptable header forms (matches Jupyter + most REST conventions):

      - ``Authorization: Bearer <token>``
      - ``Authorization: token <token>``
    """
    expected = getattr(request.app.state, "token", None)
    if not expected:
        # Misconfiguration — daemon started without loading config.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="daemon token not configured",
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="sopify"'},
        )

    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() not in ("bearer", "token"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="malformed authorization header",
            headers={"WWW-Authenticate": 'Bearer realm="sopify"'},
        )

    provided = parts[1].strip()
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="sopify"'},
        )

"""Minimal shared-secret gate for the API itself.

This exists because the frontend's password screen (PasswordGate.tsx) is
purely client-side -- it protects the UI, not the API. Once the backend
is reachable from the public internet (e.g. via a tunnel or real
hosting), anyone who finds the URL could call the API directly and
bypass that screen entirely. This dependency makes every route require
the same shared secret as a header, so the API itself isn't wide open.

This is still not a real auth system (no per-user accounts, no
rotation, a shared secret sent on every request) -- it's a floor, not a
ceiling. Real multi-user auth is out of scope until this becomes more
than a single-practitioner tool.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException

# Falls back to the same value used in the frontend's PasswordGate for
# local dev convenience; set API_SHARED_KEY explicitly wherever this is
# actually deployed so the two aren't forced to stay in lockstep.
_EXPECTED_KEY = os.environ.get("API_SHARED_KEY", "311576250")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key is None or not secrets.compare_digest(x_api_key, _EXPECTED_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")

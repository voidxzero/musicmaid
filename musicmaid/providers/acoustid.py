"""AcoustID fingerprint lookup (https://acoustid.org/webservice)."""
from __future__ import annotations

from .. import net

URL = "https://api.acoustid.org/v2/lookup"


class AcoustIDError(Exception):
    pass


def lookup(api_key: str, fingerprint: str, duration: float) -> list[dict]:
    """Return AcoustID results: [{id, score, recordings:[{id,title,duration,artists,releasegroups:[...]}]}]."""
    if not api_key:
        raise AcoustIDError("No AcoustID API key configured (get a free one at https://acoustid.org/new-application)")
    r = net.get(
        URL,
        data={
            "client": api_key,
            "duration": str(int(round(duration))),
            "fingerprint": fingerprint,
            "meta": "recordings releasegroups releases tracks compress",
            "format": "json",
        },
    )
    try:
        data = r.json()
    except ValueError as e:
        raise net.NetError(f"AcoustID returned HTTP {r.status_code}") from e
    if data.get("status") != "ok":
        msg = (data.get("error") or {}).get("message", "unknown error")
        raise AcoustIDError(f"AcoustID: {msg}")
    return data.get("results", [])


def check_key(api_key: str) -> bool | None:
    """True if AcoustID accepts the key, False if it rejects it, None if we couldn't tell (offline)."""
    if not api_key.strip():
        return False
    try:
        r = net.get(URL, data={"client": api_key.strip(), "duration": "200", "fingerprint": "AQAAAA",
                               "format": "json"}, retries=1)
        data = r.json()
    except (net.NetError, ValueError):
        return None
    err = data.get("error") or {}
    if err.get("code") == 4 or "invalid api key" in str(err.get("message", "")).lower():
        return False
    if err.get("code") == 2:  # missing parameter: shouldn't happen, can't judge
        return None
    return True

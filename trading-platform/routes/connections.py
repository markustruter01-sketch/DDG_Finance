"""GET /connections — every outside link and when it last worked and last failed.

Read this before acting on any error message: a link with a success after its
last failure is working (core/link_health.py).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

connections_router = APIRouter()


@connections_router.get("/connections")
async def connections():
    from core.link_health import read_links
    try:
        return {"links": read_links()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Link health unavailable ({type(exc).__name__})") from None

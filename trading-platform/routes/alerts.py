"""Alert system routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from notifications import alert_manager as _alert_mgr

alerts_router = APIRouter()


@alerts_router.get("/alerts/config")
async def alerts_config():
    return _alert_mgr.get_config()


@alerts_router.post("/alerts/config")
async def alerts_config_update(request: Request):
    body = await request.json()
    return _alert_mgr.save_config(body)


@alerts_router.get("/alerts/status")
async def alerts_status():
    return _alert_mgr.get_queue_status()


@alerts_router.post("/alerts/test")
async def alerts_test():
    from notifications.telegram import send_test_message, is_configured as tg_ok
    from notifications.discord import is_configured as dc_ok, _send_async, _embed, COLOR_PURPLE
    tg_result = False
    dc_result = False
    if tg_ok():
        tg_result = send_test_message()
    if dc_ok():
        try:
            _send_async({"embeds": [_embed("\U0001f514 Alert Test", "This is a test notification from AlgoEdge.", COLOR_PURPLE)]})
            dc_result = True
        except Exception:
            dc_result = False
    return {
        "telegram_configured": tg_ok(),
        "telegram_sent": tg_result,
        "discord_configured": dc_ok(),
        "discord_sent": dc_result,
        "detail": f"TG={'sent' if tg_result else 'skip'} DC={'sent' if dc_result else 'skip'}",
    }


@alerts_router.post("/alerts/flush")
async def alerts_flush():
    count = _alert_mgr.flush_alerts()
    return {"flushed": count}

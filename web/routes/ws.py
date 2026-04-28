"""WebSocket gateway for live dashboard events."""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from web.security.tokens import TokenError, decode_token
from web.services.bot_ipc import get_ipc

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def ws_gateway(websocket: WebSocket) -> None:
    token = websocket.cookies.get("cognix_access") or websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        decode_token(token, expected_type="access")
    except TokenError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    ipc = get_ipc()
    queue = ipc.subscribe_events()
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    finally:
        ipc.unsubscribe_events(queue)

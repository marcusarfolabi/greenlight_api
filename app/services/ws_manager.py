import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, Set[WebSocket]] = {}
        self.timers: Dict[str, int] = {}
        self.timer_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, access_code: str, websocket: WebSocket):
        # await websocket.accept()
        conns = self.active.setdefault(access_code, set())
        conns.add(websocket)
        logger.info(
            "WebSocket connected for access_code=%s active_connections=%s",
            access_code,
            len(conns),
        )

    def disconnect(self, access_code: str, websocket: WebSocket):
        conns = self.active.get(access_code)
        if not conns:
            return
        conns.discard(websocket)
        logger.info(
            "WebSocket disconnected for access_code=%s active_connections=%s",
            access_code,
            len(conns),
        )
        if not conns:
            # no more clients for this access code: cancel timer and cleanup
            self.active.pop(access_code, None)
            task = self.timer_tasks.pop(access_code, None)
            if task:
                task.cancel()
            self.timers.pop(access_code, None)

    def connection_count(self, access_code: str) -> int:
        return len(self.active.get(access_code, set()))

    async def broadcast(self, access_code: str, message: dict):
        conns = self.active.get(access_code, set())
        if not conns:
            logger.warning(
                "No active WebSocket connections for access_code=%s message_type=%s",
                access_code,
                message.get("type"),
            )
            return
        # Use a safe default serializer so datetime and other non-JSON types
        # are converted to strings instead of raising TypeError which would
        # prevent broadcasts from being sent.
        data = json.dumps(message, default=str)
        to_remove = []
        sent_count = 0
        for ws in list(conns):
            try:
                await ws.send_text(data)
                sent_count += 1
            except Exception:
                to_remove.append(ws)

        for ws in to_remove:
            conns.discard(ws)

        logger.info(
            "Broadcast message_type=%s access_code=%s sent=%s failed=%s active_connections=%s",
            message.get("type"),
            access_code,
            sent_count,
            len(to_remove),
            len(conns),
        )

    def start_countdown(self, access_code: str, seconds: int, broadcast_countdown_coro):
        # broadcast_countdown_coro must be an async callable accepting (access_code, remaining_seconds)
        if access_code in self.timer_tasks:
            logger.info("Countdown already running for access_code=%s", access_code)
            return False
        self.timers[access_code] = seconds

        async def _run():
            try:
                while self.timers.get(access_code, 0) > 0:
                    await asyncio.sleep(1)
                    self.timers[access_code] = max(0, self.timers.get(access_code, 0) - 1)
                    await broadcast_countdown_coro(access_code, self.timers[access_code])
                # final broadcast at 0
                await broadcast_countdown_coro(access_code, 0)
                
                await self.broadcast(access_code, {"type": "game_start", "payload": {}})
                
            except asyncio.CancelledError:
                return
            finally:
                self.timer_tasks.pop(access_code, None)
                self.timers.pop(access_code, None)

        task = asyncio.create_task(_run())
        self.timer_tasks[access_code] = task
        logger.info("Countdown task started for access_code=%s seconds=%s", access_code, seconds)
        return True


ws_manager = ConnectionManager()

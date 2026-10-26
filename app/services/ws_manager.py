import asyncio
import json
import logging
from datetime import datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, set[WebSocket]] = {}
        self.timers: dict[str, int] = {}
        self.timer_tasks: dict[str, asyncio.Task] = {}
        self.active_questions: dict[str, dict] = {}

    async def connect(self, access_code: str, websocket: WebSocket):
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
            # Cleanup internal room states when all clients leave
            self.active.pop(access_code, None)
            task = self.timer_tasks.pop(access_code, None)
            if task:
                task.cancel()
            self.timers.pop(access_code, None)
            self.active_questions.pop(access_code, None)

    def connection_count(self, access_code: str) -> int:
        return len(self.active.get(access_code, set()))

    async def close_room(self, access_code: str):
        """Close all WebSocket connections for a given access_code and cleanup timers/tasks."""
        conns = list(self.active.get(access_code, set()))

        # Cleanup internal state completely
        task = self.timer_tasks.pop(access_code, None)
        if task:
            task.cancel()
        self.timers.pop(access_code, None)
        self.active_questions.pop(access_code, None)
        self.active.pop(access_code, None)

        if not conns:
            logger.info("No connections to close for access_code=%s", access_code)
            return

        for ws in conns:
            try:
                await ws.close(code=1000)
            except Exception:
                logger.exception(
                    "Error closing websocket for access_code=%s", access_code
                )

        logger.info("Closed %s connections for access_code=%s", len(conns), access_code)

    async def broadcast(self, access_code: str, message: dict):
        conns = self.active.get(access_code, set())
        if not conns:
            logger.warning(
                "No active WebSocket connections for access_code=%s message_type=%s",
                access_code,
                message.get("type"),
            )
            return

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
        if access_code in self.timer_tasks:
            logger.info("Countdown already running for access_code=%s", access_code)
            return False
        self.timers[access_code] = seconds

        async def _run():
            try:
                while self.timers.get(access_code, 0) > 0:
                    await asyncio.sleep(1)
                    self.timers[access_code] = max(
                        0, self.timers.get(access_code, 0) - 1
                    )
                    await broadcast_countdown_coro(
                        access_code, self.timers[access_code]
                    )
                await broadcast_countdown_coro(access_code, 0)
                await self.broadcast(access_code, {"type": "game_start", "payload": {}})

            except asyncio.CancelledError:
                return
            finally:
                self.timer_tasks.pop(access_code, None)
                self.timers.pop(access_code, None)

        task = asyncio.create_task(_run())
        self.timer_tasks[access_code] = task
        logger.info(
            "Countdown task started for access_code=%s seconds=%s", access_code, seconds
        )
        return True

    def set_active_question(self, access_code: str, question_data: dict):
        """Save active question payload and timestamp for mid-game sync."""
        self.active_questions[str(access_code)] = {
            "question": question_data.get("question"),
            "question_index": question_data.get("question_index", 0),
            "started_at": datetime.utcnow().timestamp(),
            "time_limit_seconds": question_data.get("question", {}).get(
                "time_limit_seconds", 30
            ),
        }

    def clear_active_question(self, access_code: str):
        self.active_questions.pop(str(access_code), None)


ws_manager = ConnectionManager()

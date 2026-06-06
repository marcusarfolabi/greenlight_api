import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, Set[WebSocket]] = {}
        self.timers: Dict[str, int] = {}
        self.timer_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, access_code: str, websocket: WebSocket):
        # await websocket.accept()
        conns = self.active.setdefault(access_code, set())
        conns.add(websocket)

    def disconnect(self, access_code: str, websocket: WebSocket):
        conns = self.active.get(access_code)
        if not conns:
            return
        conns.discard(websocket)
        if not conns:
            # no more clients for this access code: cancel timer and cleanup
            self.active.pop(access_code, None)
            task = self.timer_tasks.pop(access_code, None)
            if task:
                task.cancel()
            self.timers.pop(access_code, None)

    async def broadcast(self, access_code: str, message: dict):
        conns = self.active.get(access_code, set())
        if not conns:
            return
        data = json.dumps(message)
        to_remove = []
        for ws in list(conns):
            try:
                await ws.send_text(data)
            except Exception:
                to_remove.append(ws)

        for ws in to_remove:
            conns.discard(ws)

    def start_countdown(self, access_code: str, seconds: int, broadcast_countdown_coro):
        # broadcast_countdown_coro must be an async callable accepting (access_code, remaining_seconds)
        if access_code in self.timer_tasks:
            return
        self.timers[access_code] = seconds

        async def _run():
            try:
                while self.timers.get(access_code, 0) > 0:
                    await asyncio.sleep(1)
                    self.timers[access_code] = max(0, self.timers.get(access_code, 0) - 1)
                    await broadcast_countdown_coro(access_code, self.timers[access_code])
                # final broadcast at 0
                await broadcast_countdown_coro(access_code, 0)
                
                # Broadcast game start signal when countdown completes
                await self.broadcast(access_code, {"type": "game_start", "payload": {}})
                
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(_run())
        self.timer_tasks[access_code] = task


ws_manager = ConnectionManager()

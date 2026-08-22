import logging
from contextlib import suppress
from datetime import datetime

from fastapi import (
    APIRouter,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session

from app.models.arena import Arena
from app.models.organization import ArenaPayoutReport
from app.models.player import Player, PlayerAnswerScore
from app.schemas.player import (
    PlayerScoreboardResponse,
)
from app.services.ws_manager import ws_manager
from app.utils.arenautil import (
    _new_players_session_id,
    _players_for_arena_session_query,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Upload limits
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PDF_PAGES = 50


def get_arena_scoreboard(
    arena_id: str,
    db: Session,
):
    """Helper function to calculate scoreboard for an arena with all player scores ranked"""
    from app.models.player import PlayerAnswerScore

    arena = db.query(Arena).filter(Arena.id == arena_id).first()
    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )
    players = _players_for_arena_session_query(db, arena).all()

    scoreboard_data = []
    for player in players:
        answers = (
            db.query(PlayerAnswerScore)
            .filter(
                PlayerAnswerScore.player_id == player.id,
                PlayerAnswerScore.arena_id == arena_id,
            )
            .all()
        )

        total_score = sum(a.points_earned for a in answers)
        correct_count = sum(1 for a in answers if a.is_correct)
        total_answers = len(answers)
        accuracy = (correct_count / total_answers * 100) if total_answers > 0 else 0
        last_answered = (
            max([a.answered_at for a in answers], default=None) if answers else None
        )

        scoreboard_data.append(
            {
                "player_id": player.id,
                "username": player.username or f"Player_{player.id}",
                "total_score": total_score,
                "answers_correct": correct_count,
                "answers_total": total_answers,
                "accuracy_percentage": round(accuracy, 2),
                "last_answered_at": last_answered,
                "rank": None,  # Will be set after sorting
            }
        )

    # Sort by total score descending, then by accuracy descending, then by answer time ascending
    scoreboard_data.sort(
        key=lambda x: (
            -x["total_score"],
            -x["accuracy_percentage"],
            x["last_answered_at"] or datetime.max,
        ),
    )

    # Add ranks after sorting
    for idx, entry in enumerate(scoreboard_data, 1):
        entry["rank"] = idx

    # Convert to response models
    return [PlayerScoreboardResponse.model_validate(entry) for entry in scoreboard_data]


async def close_arena_and_build_payout_ledger(arena_id: str, db: Session) -> dict:
    arena = db.query(Arena).filter(Arena.id == arena_id).first()
    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )

    players = _players_for_arena_session_query(db, arena).all()

    if not players:
        return {
            "scoreboard": [],
            "completed_players": 0,
            "completion_rate": 0.0,
        }

    ranked_players: list[dict] = []
    now = datetime.utcnow()

    for player in players:
        answers = (
            db.query(PlayerAnswerScore)
            .filter(
                PlayerAnswerScore.player_id == player.id,
                PlayerAnswerScore.arena_id == arena_id,
            )
            .all()
        )

        total_score = sum(a.points_earned for a in answers)
        answers_submitted = len(answers)
        correct_answers = sum(1 for a in answers if a.is_correct)
        accuracy_percentage = (
            round((correct_answers / answers_submitted) * 100, 2)
            if answers_submitted > 0
            else 0.0
        )

        player.score = total_score
        player.answers_submitted = answers_submitted
        player.correct_answers = correct_answers

        # Treat a player as completed if they participated in at least one question.
        if answers_submitted > 0:
            player.status = "completed"
            if player.completed_at is None:
                player.completed_at = now

        ranked_players.append(
            {
                "player": player,
                "player_id": player.id,
                "username": player.username or f"Player_{player.id}",
                "total_score": total_score,
                "answers_correct": correct_answers,
                "answers_total": answers_submitted,
                "accuracy_percentage": accuracy_percentage,
                "rank": None,
            }
        )

    ranked_players.sort(
        key=lambda entry: (
            -(entry["total_score"] or 0),
            -(entry["answers_correct"] or 0),
            (entry["username"] or "").lower(),
        )
    )

    for index, entry in enumerate(ranked_players, start=1):
        entry["rank"] = index
        entry["player"].rank = index

    # 3. Define your prize pool matrix structure (Example calculation model)
    # Top 1 gets 50%, Top 2 gets 30%, Top 3 gets 20% of a $50 pool (calculated in cents)
    prize_pool_cents = 5000
    payout_distribution = {
        1: int(prize_pool_cents * 0.50),
        2: int(prize_pool_cents * 0.30),
        3: int(prize_pool_cents * 0.20),
    }

    existing_reports = {
        report.player_id: report
        for report in db.query(ArenaPayoutReport)
        .filter(ArenaPayoutReport.arena_id == arena_id)
        .all()
    }

    eligible_for_payout = [
        entry for entry in ranked_players if (entry["answers_total"] or 0) > 0
    ]

    # 4. Generate or update payout records for participants.
    for entry in eligible_for_payout:
        player = entry["player"]
        current_rank = entry["rank"]
        payout_reward = payout_distribution.get(current_rank, 0)

        existing = existing_reports.get(player.id)
        if existing:
            existing.username = player.username or f"Player_{player.id}"
            existing.final_score = entry["total_score"]
            existing.final_rank = current_rank
            existing.payout_amount_cents = payout_reward
            existing.payout_status = "pending" if payout_reward > 0 else "skipped"
        else:
            payout_entry = ArenaPayoutReport(
                arena_id=arena_id,
                player_id=player.id,
                username=player.username or f"Player_{player.id}",
                final_score=entry["total_score"],
                final_rank=current_rank,
                payout_amount_cents=payout_reward,
                payout_status="pending" if payout_reward > 0 else "skipped",
            )
            db.add(payout_entry)

    total_players = len(ranked_players)
    completed_players = sum(
        1 for entry in ranked_players if (entry["answers_total"] or 0) > 0
    )
    completion_rate = (
        round((completed_players / total_players) * 100, 2)
        if total_players > 0
        else 0.0
    )

    db.commit()

    # Prepare a fresh session tag for the next time this arena is played.
    arena.players_session_id = _new_players_session_id()
    db.add(arena)
    db.commit()

    return {
        "scoreboard": [
            {
                "player_id": entry["player_id"],
                "username": entry["username"],
                "total_score": entry["total_score"],
                "answers_correct": entry["answers_correct"],
                "answers_total": entry["answers_total"],
                "accuracy_percentage": entry["accuracy_percentage"],
                "rank": entry["rank"],
            }
            for entry in ranked_players
        ],
        "completed_players": completed_players,
        "completion_rate": completion_rate,
    }


@router.websocket("/ws/lobby/{access_code}")
async def lobby_websocket(websocket: WebSocket, access_code: str):
    """WebSocket endpoint for real-time lobby updates and shared countdown."""

    # Accept the connection
    await websocket.accept()
    await ws_manager.connect(str(access_code), websocket)

    player_info: dict = {"player_id": 0, "player_name": "", "arena_id": ""}

    try:
        from app.db.session import get_db as _get_db

        db_gen = _get_db()
        db = next(db_gen)

        try:
            arena = db.query(Arena).filter(Arena.access_code == access_code).first()
            if not arena:
                await websocket.close(code=1008)
                return

            player_info["arena_id"] = arena.id

            # Fetch players based on arena ID
            players = _players_for_arena_session_query(db, arena).all()
            players_list = [{"id": p.id, "username": p.username} for p in players]

            payload = {
                "type": "lobby_update",
                "payload": {
                    "players": players_list,
                    "total_players": len(players_list),
                    "lobby_waiting_time": 30,
                    "arena_name": arena.arena_name,
                    "arena_access_code": arena.access_code,
                },
            }

            await ws_manager.broadcast(str(arena.access_code), payload)

            async def _countdown_broadcast(ac, remaining):
                await ws_manager.broadcast(
                    ac, {"type": "countdown", "payload": {"countdown": remaining}}
                )

            # Listen for incoming messages
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "register_player":
                    try:
                        payload = data.get("payload", {})
                        player_name = payload.get("player_name")

                        if player_name:
                            player = (
                                db.query(Player)
                                .filter(
                                    Player.arena_id == arena.id,
                                    Player.session_id == arena.players_session_id,
                                    Player.username == player_name,
                                )
                                .first()
                            )

                            if player:
                                player_info["player_id"] = player.id
                                player_info["player_name"] = player_name
                                logger.info(
                                    f"Player {player_name} (ID: {player.id}) registered in arena {arena.id}"
                                )
                    except Exception:
                        logger.exception("Error handling player registration")

                elif msg_type == "update_avatar":
                    try:
                        payload = data.get("payload", {})
                        avatar_style = payload.get("avatarStyle")
                        player_id = payload.get("player_id") or player_info.get(
                            "player_id"
                        )

                        if player_id:
                            # 1. Update the avatar column on the existing Player record
                            player = (
                                db.query(Player).filter(Player.id == player_id).first()
                            )
                            if player:
                                player.avatar = avatar_style
                                db.commit()

                        # 2. Query all players for the arena session and build the payload
                        players = _players_for_arena_session_query(db, arena).all()
                        players_list = [
                            {
                                "id": p.id,
                                "username": p.username,
                                "avatar": p.avatar,  # Reads avatar directly from DB column
                            }
                            for p in players
                        ]

                        # 3. Broadcast updated players list to all connected clients
                        await ws_manager.broadcast(
                            str(arena.access_code),
                            {
                                "type": "lobby_update",
                                "payload": {
                                    "players": players_list,
                                    "total_players": len(players_list),
                                    "arena_name": arena.arena_name,
                                    "arena_access_code": arena.access_code,
                                },
                            },
                        )
                        logger.info(
                            f"Updated avatar for Player ID {player_id} to '{avatar_style}'"
                        )
                    except Exception:
                        logger.exception("Error handling update_avatar message")

                elif msg_type == "host_ready":
                    try:
                        seconds = int(data.get("seconds", 30))
                        ws_manager.start_countdown(
                            str(arena.access_code), seconds, _countdown_broadcast
                        )
                    except Exception:
                        logger.exception("Error handling host_ready message")

                elif msg_type == "question_display":
                    try:
                        await ws_manager.broadcast(
                            str(arena.access_code),
                            {
                                "type": "question_display",
                                "payload": data.get("payload", {}),
                            },
                        )
                    except Exception:
                        logger.exception("Error broadcasting question")

                # elif msg_type == "player_answer":
                #     try:
                #         payload = data.get("payload", {})
                #         question_id = payload.get("question_id")
                #         answer_selected = payload.get("answer_selected")
                #         is_correct = payload.get("is_correct")
                #         time_taken = payload.get("time_taken", 0)
                #         question_time_limit = payload.get("question_time_limit", 0)
                #         max_points = payload.get("max_points", 0)

                #         points_earned = PlayerAnswerScore.calculate_score(
                #             time_taken=time_taken,
                #             question_time_limit=question_time_limit,
                #             max_points=max_points,
                #             is_correct=is_correct,
                #         )

                #         # Save answer to database if player is registered
                #         if player_info["player_id"] and player_info["arena_id"]:
                #             answer_score = PlayerAnswerScore(
                #                 player_id=player_info["player_id"],
                #                 arena_id=player_info["arena_id"],
                #                 question_id=question_id,
                #                 answer_selected=answer_selected,
                #                 is_correct=is_correct,
                #                 time_taken=time_taken,
                #                 question_time_limit=question_time_limit,
                #                 points_earned=points_earned,
                #                 max_points=max_points,
                #             )
                #             db.add(answer_score)
                #             db.commit()
                #             logger.info(
                #                 f"Saved answer for player {player_info['player_name']} on Q{question_id}: {points_earned} points"
                #             )

                #         await ws_manager.broadcast(
                #             str(arena.access_code),
                #             {
                #                 "type": "player_score_update",
                #                 "payload": {
                #                     "question_id": question_id,
                #                     "player_name": player_info["player_name"],
                #                     "answer_selected": answer_selected,
                #                     "is_correct": is_correct,
                #                     "time_taken": time_taken,
                #                     "points_earned": points_earned,
                #                 },
                #             },
                #         )

                #         logger.info(
                #             f"Player {player_info['player_name']} answered Q{question_id} correctly={is_correct} in {time_taken}s, earned {points_earned} points"
                #         )
                #     except Exception:
                #         logger.exception("Error processing player answer")

                elif msg_type == "player_answer":
                    try:
                        payload = data.get("payload", {})
                        question_id = payload.get("question_id")
                        answer_selected = payload.get("answer_selected")
                        is_correct = payload.get("is_correct")
                        time_taken = payload.get("time_taken", 0)
                        question_time_limit = payload.get("question_time_limit", 0)
                        max_points = payload.get("max_points", 0)

                        points_earned = PlayerAnswerScore.calculate_score(
                            time_taken=time_taken,
                            question_time_limit=question_time_limit,
                            max_points=max_points,
                            is_correct=is_correct,
                        )

                        # Save answer to database if player is registered
                        if player_info["player_id"] and player_info["arena_id"]:
                            answer_score = PlayerAnswerScore(
                                player_id=player_info["player_id"],
                                arena_id=player_info["arena_id"],
                                question_id=question_id,
                                answer_selected=answer_selected,
                                is_correct=is_correct,
                                time_taken=time_taken,
                                question_time_limit=question_time_limit,
                                points_earned=points_earned,
                                max_points=max_points,
                            )
                            db.add(answer_score)
                            db.commit()
                            logger.info(
                                f"Saved answer for player {player_info['player_name']} on Q{question_id}: {points_earned} points"
                            )

                        # Broadcast the individual score update
                        await ws_manager.broadcast(
                            str(arena.access_code),
                            {
                                "type": "player_score_update",
                                "payload": {
                                    "question_id": question_id,
                                    "player_name": player_info["player_name"],
                                    "answer_selected": answer_selected,
                                    "is_correct": is_correct,
                                    "time_taken": time_taken,
                                    "points_earned": points_earned,
                                },
                            },
                        )

                        session_players = _players_for_arena_session_query(db, arena)

                        # 2. Total registered players count
                        total_registered_players = session_players.count()

                        # 3. Count distinct answers strictly for players in this session
                        answered_players_count = (
                            db.query(PlayerAnswerScore.player_id)
                            .filter(
                                PlayerAnswerScore.arena_id == arena.id,
                                PlayerAnswerScore.question_id == question_id,
                                PlayerAnswerScore.player_id.in_(
                                    session_players.with_entities(
                                        Player.id
                                    )  # <--- Pass the subquery targeting IDs
                                ),
                            )
                            .distinct()
                            .count()
                        )

                        logger.info(
                            f"Q{question_id} Status: {answered_players_count}/{total_registered_players} answered for access_code={arena.access_code}"
                        )

                        # 3. Only terminate early if EVERY registered player has answered
                        if (
                            total_registered_players > 0
                            and answered_players_count >= total_registered_players
                        ):
                            logger.info(
                                f"All {total_registered_players} registered players answered Q{question_id}. Early terminating timer."
                            )

                            access_code_str = str(arena.access_code)
                            task = ws_manager.timer_tasks.pop(access_code_str, None)
                            if task:
                                task.cancel()
                            ws_manager.timers.pop(access_code_str, None)

                            scoreboard = get_arena_scoreboard(arena.id, db)

                            await ws_manager.broadcast(
                                access_code_str,
                                {
                                    "type": "all_players_answered",
                                    "payload": {
                                        "question_id": question_id,
                                        "scoreboard": [
                                            entry.model_dump() for entry in scoreboard
                                        ],
                                    },
                                },
                            )
                    except Exception:
                        logger.exception("Error processing player answer")

                elif msg_type == "hide_question":
                    # Hide question from all connected clients
                    try:
                        await ws_manager.broadcast(
                            str(arena.access_code),
                            {"type": "hide_question", "payload": {}},
                        )
                    except Exception:
                        logger.exception("Error hiding question")

                elif msg_type == "question_timeout":
                    try:
                        scoreboard = get_arena_scoreboard(arena.id, db)
                        await ws_manager.broadcast(
                            str(arena.access_code),
                            {
                                "type": "scoreboard_update",
                                "payload": {
                                    "scoreboard": [
                                        entry.model_dump() for entry in scoreboard
                                    ]
                                },
                            },
                        )
                        logger.info(
                            f"Broadcasted scoreboard for arena {arena.id} due to question timeout"
                        )
                    except Exception:
                        logger.exception("Error broadcasting scoreboard on timeout")

                elif msg_type == "end_game" or msg_type == "game_over":
                    try:
                        finalization = await close_arena_and_build_payout_ledger(
                            arena_id=arena.id, db=db
                        )

                        await ws_manager.broadcast(
                            str(arena.access_code),
                            {
                                "type": "arena_concluded",
                                "payload": {
                                    "message": "Game over! Financial payout ledger generated.",
                                    "scoreboard": finalization.get("scoreboard", []),
                                    "completed_players": finalization.get(
                                        "completed_players", 0
                                    ),
                                    "completion_rate": finalization.get(
                                        "completion_rate", 0.0
                                    ),
                                },
                            },
                        )
                        # Close all websocket connections for this arena to avoid lingering sockets
                        try:
                            await ws_manager.close_room(str(arena.access_code))
                        except Exception:
                            logger.exception(
                                "Error closing websockets for arena %s", arena.id
                            )
                    except Exception as e:
                        logger.exception(
                            f"Critical payout calculation failure on arena {arena.id}: {e}"
                        )

        finally:
            try:
                next(db_gen, None)
            except StopIteration:
                pass

    except WebSocketDisconnect:
        ws_manager.disconnect(str(access_code), websocket)
    except Exception as exc:
        logger.exception(
            "Unexpected websocket error for access_code %s: %s", access_code, exc
        )
        ws_manager.disconnect(str(access_code), websocket)
        with suppress(Exception):
            await websocket.close()

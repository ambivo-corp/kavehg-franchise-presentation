"""
Chat SSE proxy — streams answers from vectordb for a presentation's KB
Parses VectorDB JSON events and emits clean SSE to the browser.
"""
import json
import time
import uuid
import logging
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db import get_db
from app.models.presentation import ChatRequest
from app.services import kb_service
from app.services.quota_service import check_genai_quota, check_daily_chat_limit, record_chat_query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

# Simple in-memory rate limiter: {ip: [timestamps]}
_rate: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 30  # messages per minute
RATE_WINDOW = 60  # seconds


def _check_rate(ip: str):
    now = time.time()
    timestamps = _rate[ip]
    _rate[ip] = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(_rate[ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
    _rate[ip].append(now)


@router.post("/{presentation_id}")
async def chat(presentation_id: str, body: ChatRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate(client_ip)

    from bson import ObjectId

    coll = get_db()["content_presentations"]
    doc = await coll.find_one({"_id": ObjectId(presentation_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Presentation not found")
    if not doc.get("chat_enabled", True):
        raise HTTPException(status_code=403, detail="Chat is disabled for this page")

    kb_name = doc["kb_name"]
    tenant_id = doc["tenant_id"]
    user_id = doc.get("userid") or doc.get("user_id", "")
    session_id = body.session_id or uuid.uuid4().hex
    access_code = request.cookies.get(f"cp_access_{doc['slug']}")

    # --- Quota & limit checks ---
    quota = await check_genai_quota(tenant_id)
    if not quota.get("allowed", True):
        raise HTTPException(
            status_code=402,
            detail=quota.get("error", "GenAI quota exhausted. Please add a payment method."),
        )

    if not await check_daily_chat_limit(presentation_id):
        raise HTTPException(
            status_code=429,
            detail=f"Daily chat limit ({settings.daily_chat_limit} queries) reached for this page. Try again tomorrow.",
        )

    async def event_generator():
        # Send session_id first so client can cache it for conversation memory
        yield {"event": "session", "data": session_id}

        # Record the chat query (fire-and-forget inside the stream)
        try:
            await record_chat_query(
                presentation_id, tenant_id, kb_name, session_id, body.message, client_ip,
                access_code=access_code,
            )
        except Exception as rec_exc:
            logger.warning("Failed to record chat query: %s", rec_exc)

        try:
            async for line in kb_service.query_kb_stream(
                kb_name, body.message, session_id, tenant_id, user_id
            ):
                # Each line from VectorDB is "data: {json}" — extract the JSON
                raw = line
                if raw.startswith("data:"):
                    raw = raw[5:].strip()
                if not raw:
                    continue

                # Try to parse as JSON
                try:
                    evt = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    logger.debug(
                        "Skipped non-JSON line: %.200s  kb=%s presentation=%s",
                        raw, kb_name, presentation_id,
                    )
                    continue

                evt_type = evt.get("type", "")

                if evt_type == "stream_chunk":
                    text = evt.get("text", "")
                    if text:
                        yield {"event": "chunk", "data": text}

                elif evt_type == "stream_start":
                    yield {"event": "start", "data": ""}

                elif evt_type == "stream_complete":
                    yield {"event": "done", "data": ""}
                    return

                elif evt_type == "stream_error":
                    error_msg = evt.get("error", "Unknown error")
                    logger.error(f"VectorDB stream error for kb={kb_name}: {error_msg}")
                    yield {"event": "error", "data": error_msg}
                    return

                else:
                    logger.debug(
                        "Unrecognized event type=%s  kb=%s presentation=%s",
                        evt_type, kb_name, presentation_id,
                    )

        except Exception as exc:
            logger.exception(
                "Chat stream error: %s(%s)  kb=%s tenant=%s presentation=%s",
                type(exc).__name__, exc, kb_name, tenant_id, presentation_id,
            )
            yield {"event": "error", "data": "An error occurred while generating the response."}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())

"""
VectorDB Knowledge Base service — create, index, delete, query (streaming)
"""
import logging
from typing import AsyncIterator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE = settings.vectordb_api_url.rstrip("/")
TIMEOUT = httpx.Timeout(30.0, read=120.0)


def _headers(tenant_id: str, user_id: str) -> dict:
    h = {
        "Content-Type": "application/json",
        "X-AMBIVO-INTERNAL-SECRET": settings.ambivo_internal_secret,
    }
    if tenant_id:
        h["X-TENANT-ID"] = tenant_id
    if user_id:
        h["X-USER-ID"] = user_id
    return h


async def create_kb(kb_name: str, tenant_id: str, user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{BASE}/kh/collection",
            headers=_headers(tenant_id, user_id),
            json={"kb_name": kb_name, "tenant_id": tenant_id, "userid": user_id},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Created KB: {kb_name}")
        return data


async def index_text(
    kb_name: str,
    text: str,
    tenant_id: str,
    user_id: str,
    display_file_name: str = "content",
) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{BASE}/kh/index_text",
            headers=_headers(tenant_id, user_id),
            json={
                "kb_name": kb_name,
                "text": text,
                "display_file_name": display_file_name,
                "tenant_id": tenant_id,
                "userid": user_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Indexed text into KB: {kb_name} ({len(text)} chars)")
        return data


async def delete_kb(kb_name: str, tenant_id: str, user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Try /kh/collection first (matches create endpoint)
        resp = await client.delete(
            f"{BASE}/kh/collection",
            headers=_headers(tenant_id, user_id),
            params={"kb_name": kb_name, "action": "delete"},
        )
        if resp.status_code >= 400:
            logger.warning(
                "delete_kb via /kh/collection failed (status=%s), trying /pgv/collection fallback for kb=%s",
                resp.status_code, kb_name,
            )
            # Fallback to /pgv/collection
            resp = await client.delete(
                f"{BASE}/pgv/collection",
                headers=_headers(tenant_id, user_id),
                params={"kb_name": kb_name, "action": "delete"},
            )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Deleted KB: {kb_name}")
        return data


async def truncate_kb(kb_name: str, tenant_id: str, user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.delete(
            f"{BASE}/pgv/collection",
            headers=_headers(tenant_id, user_id),
            params={"kb_name": kb_name, "action": "truncate"},
        )
        if resp.status_code >= 400:
            logger.error(
                "truncate_kb failed: status=%s body=%s kb_name=%s tenant_id=%s",
                resp.status_code, resp.text[:1000], kb_name, tenant_id,
            )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Truncated KB: {kb_name}")
        return data


async def query_kb_stream(
    kb_name: str,
    question: str,
    session_id: str,
    tenant_id: str,
    user_id: str,
) -> AsyncIterator[str]:
    """Stream SSE chunks from vectordb /kh/get_answer."""
    url = f"{BASE}/kh/get_answer"
    logger.info(
        "query_kb_stream → POST %s  kb_name=%s tenant_id=%s session_id=%s",
        url, kb_name, tenant_id, session_id,
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0)) as client:
            async with client.stream(
                "POST",
                url,
                headers=_headers(tenant_id, user_id),
                json={
                    "kb_name": kb_name,
                    "question": question,
                    "session_id": session_id,
                    "streaming": True,
                    "tenant_id": tenant_id,
                    "userid": user_id,
                },
            ) as resp:
                logger.info(
                    "query_kb_stream ← status=%s headers=%s",
                    resp.status_code,
                    dict(resp.headers),
                )
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        logger.debug("SSE line: %s", line[:500])
                        yield line
    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response else "<no body>"
        logger.error(
            "query_kb_stream HTTP error: status=%s body=%s kb_name=%s tenant_id=%s",
            exc.response.status_code, body[:1000], kb_name, tenant_id,
        )
        raise
    except httpx.TimeoutException:
        logger.error(
            "query_kb_stream timeout: kb_name=%s tenant_id=%s", kb_name, tenant_id,
        )
        raise
    except Exception:
        logger.exception(
            "query_kb_stream unexpected error: kb_name=%s tenant_id=%s", kb_name, tenant_id,
        )
        raise

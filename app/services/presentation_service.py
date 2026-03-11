"""
Presentation CRUD + KB lifecycle
"""
import logging
import re
import secrets
import string
from datetime import datetime, timezone

from bson import ObjectId
from slugify import slugify

from app.db import get_db
from app.models.presentation import PresentationCreate, PresentationUpdate, PresentationResponse, PresentationDetail, HeaderConfig
from app.services import kb_service
from app.config import settings

logger = logging.getLogger(__name__)
COLLECTION = "content_presentations"


_CODE_CHARS = string.ascii_uppercase + string.digits  # A-Z, 0-9
_CODE_RE = re.compile(r'^[A-Z0-9]{3,12}$')


def _validate_access_codes(codes: list[str]) -> list[str]:
    """Normalize to uppercase, deduplicate, and validate access codes."""
    seen = set()
    result = []
    for code in codes:
        code = code.strip().upper()
        if not _CODE_RE.match(code):
            raise ValueError(f"Invalid access code '{code}': must be 3-12 characters, A-Z and 0-9 only")
        if code not in seen:
            seen.add(code)
            result.append(code)
    return sorted(result)


def _generate_access_codes(count: int = 3) -> list[str]:
    """Generate unique 6-char alphanumeric access codes."""
    codes = set()
    while len(codes) < count:
        codes.add("".join(secrets.choice(_CODE_CHARS) for _ in range(6)))
    return sorted(codes)


def _kb_name(tenant_id: str, slug: str) -> str:
    return f"content_{tenant_id[:8]}_{slug}"


def _build_header(doc: dict, base_url: str = "") -> HeaderConfig:
    h = doc.get("header") or {}
    has_logo = doc.get("has_header_logo", False)
    logo_url = f"{base_url}/p/{doc['slug']}/logo" if has_logo else None
    return HeaderConfig(
        enabled=h.get("enabled", False),
        logo_url=logo_url,
        link_url=h.get("link_url"),
        link_text=h.get("link_text"),
        email=h.get("email"),
        phone=h.get("phone"),
        text=h.get("text"),
    )


def _doc_to_response(doc: dict, base_url: str = "", stats: dict | None = None) -> PresentationResponse:
    s = stats or {}
    return PresentationResponse(
        id=str(doc["_id"]),
        tenant_id=doc["tenant_id"],
        title=doc["title"],
        slug=doc["slug"],
        hosted_url=f"{base_url}/p/{doc['slug']}" if base_url else f"/p/{doc['slug']}",
        kb_name=doc["kb_name"],
        is_published=doc.get("is_published", True),
        chat_enabled=doc.get("chat_enabled", True),
        access_protected=doc.get("access_protected", False),
        access_codes=doc.get("access_codes", []),
        header=_build_header(doc, base_url),
        description=doc.get("description"),
        tags=doc.get("tags", []),
        created_at=doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
        updated_at=doc["updated_at"].isoformat() if isinstance(doc["updated_at"], datetime) else str(doc["updated_at"]),
        num_views=doc.get("num_views", 0),
        total_chat_queries=s.get("total", 0),
        today_chat_queries=s.get("today", 0),
    )


def _doc_to_detail(doc: dict, base_url: str = "", stats: dict | None = None) -> PresentationDetail:
    s = stats or {}
    return PresentationDetail(
        id=str(doc["_id"]),
        tenant_id=doc["tenant_id"],
        title=doc["title"],
        slug=doc["slug"],
        hosted_url=f"{base_url}/p/{doc['slug']}" if base_url else f"/p/{doc['slug']}",
        kb_name=doc["kb_name"],
        is_published=doc.get("is_published", True),
        chat_enabled=doc.get("chat_enabled", True),
        access_protected=doc.get("access_protected", False),
        access_codes=doc.get("access_codes", []),
        header=_build_header(doc, base_url),
        description=doc.get("description"),
        tags=doc.get("tags", []),
        created_at=doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
        updated_at=doc["updated_at"].isoformat() if isinstance(doc["updated_at"], datetime) else str(doc["updated_at"]),
        markdown_content=doc.get("markdown_content", ""),
        num_views=doc.get("num_views", 0),
        total_chat_queries=s.get("total", 0),
        today_chat_queries=s.get("today", 0),
    )


async def _chat_query_stats(presentation_ids: list[str]) -> dict[str, dict]:
    """Return {presentation_id: {"total": N, "today": N}} for the given IDs."""
    if not presentation_ids:
        return {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    coll = get_db()["content_chat_queries"]

    # Total counts per presentation
    pipeline_total = [
        {"$match": {"presentation_id": {"$in": presentation_ids}}},
        {"$group": {"_id": "$presentation_id", "total": {"$sum": 1}}},
    ]
    # Today counts per presentation
    pipeline_today = [
        {"$match": {"presentation_id": {"$in": presentation_ids}, "date": today}},
        {"$group": {"_id": "$presentation_id", "today": {"$sum": 1}}},
    ]

    totals = {r["_id"]: r["total"] async for r in coll.aggregate(pipeline_total)}
    todays = {r["_id"]: r["today"] async for r in coll.aggregate(pipeline_today)}

    return {
        pid: {"total": totals.get(pid, 0), "today": todays.get(pid, 0)}
        for pid in presentation_ids
    }


async def _ensure_indexes():
    coll = get_db()[COLLECTION]
    await coll.create_index("slug", unique=True)
    await coll.create_index("tenant_id")


async def _unique_slug(base_slug: str) -> str:
    coll = get_db()[COLLECTION]
    slug = base_slug
    while await coll.find_one({"slug": slug}):
        slug = f"{base_slug}-{secrets.token_hex(3)}"
    return slug


async def create(
    tenant_id: str, user_id: str, data: PresentationCreate, base_url: str = ""
) -> PresentationResponse:
    await _ensure_indexes()
    coll = get_db()[COLLECTION]

    slug = await _unique_slug(slugify(data.slug or data.title))
    kb_name = _kb_name(tenant_id, slug)

    # Create KB + index content
    try:
        await kb_service.create_kb(kb_name, tenant_id, user_id)
        await kb_service.index_text(kb_name, data.markdown_content, tenant_id, user_id, display_file_name=data.title)
    except Exception:
        logger.exception(f"KB creation/indexing failed for {kb_name}")
        raise

    access_codes = _generate_access_codes(data.num_access_codes) if data.access_protected else []

    now = datetime.now(timezone.utc)
    doc = {
        "tenant_id": tenant_id,
        "userid": user_id,
        "title": data.title,
        "slug": slug,
        "markdown_content": data.markdown_content,
        "kb_name": kb_name,
        "is_published": True,
        "chat_enabled": data.chat_enabled,
        "access_protected": data.access_protected,
        "access_codes": access_codes,
        "description": data.description,
        "tags": data.tags,
        "header": data.header.model_dump(exclude_none=True) if data.header else {},
        "created_at": now,
        "updated_at": now,
    }
    result = await coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    logger.info(f"Created presentation '{data.title}' slug={slug} kb={kb_name}")
    return _doc_to_response(doc, base_url)


async def update(
    presentation_id: str, tenant_id: str, data: PresentationUpdate, base_url: str = ""
) -> PresentationResponse:
    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"_id": ObjectId(presentation_id), "tenant_id": tenant_id})
    if not doc:
        raise ValueError("Presentation not found")

    updates: dict = {}
    if data.title is not None:
        updates["title"] = data.title
    if data.description is not None:
        updates["description"] = data.description
    if data.tags is not None:
        updates["tags"] = data.tags
    if data.chat_enabled is not None:
        updates["chat_enabled"] = data.chat_enabled

    if data.markdown_content is not None and data.markdown_content != doc.get("markdown_content"):
        updates["markdown_content"] = data.markdown_content
        # Re-index KB
        kb_name = doc["kb_name"]
        kb_user_id = doc.get("userid", doc.get("user_id", ""))
        try:
            await kb_service.truncate_kb(kb_name, tenant_id, kb_user_id)
        except Exception:
            logger.warning(f"Truncate failed for {kb_name}, falling back to delete+create")
            try:
                await kb_service.delete_kb(kb_name, tenant_id, kb_user_id)
                await kb_service.create_kb(kb_name, tenant_id, kb_user_id)
            except Exception:
                logger.exception(f"Fallback delete+create failed for {kb_name}")
                raise
        try:
            await kb_service.index_text(
                kb_name, data.markdown_content, tenant_id, kb_user_id,
                display_file_name=data.title or doc["title"],
            )
        except Exception:
            logger.exception(f"KB index_text failed for {kb_name}")
            raise

    # Access protection — direct code management
    if data.access_codes is not None:
        updates["access_codes"] = _validate_access_codes(data.access_codes)
        updates["access_protected"] = len(updates["access_codes"]) > 0

    # Access protection toggle (only auto-generate when codes weren't explicitly provided)
    if data.access_protected is not None and data.access_codes is None:
        updates["access_protected"] = data.access_protected
        if data.access_protected and not doc.get("access_codes"):
            updates["access_codes"] = _generate_access_codes(3)
        elif not data.access_protected:
            updates["access_codes"] = []

    if data.regenerate_codes is not None and data.regenerate_codes > 0:
        updates["access_codes"] = _generate_access_codes(data.regenerate_codes)
        updates["access_protected"] = True

    # Header
    if data.header is not None:
        existing_header = doc.get("header") or {}
        header_update = data.header.model_dump(exclude_none=True)
        existing_header.update(header_update)
        updates["header"] = existing_header

    if not updates:
        return _doc_to_response(doc, base_url)

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"_id": doc["_id"]}, {"$set": updates})
    doc.update(updates)
    return _doc_to_response(doc, base_url)


async def delete(presentation_id: str, tenant_id: str) -> bool:
    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"_id": ObjectId(presentation_id), "tenant_id": tenant_id})
    if not doc:
        raise ValueError("Presentation not found")

    try:
        await kb_service.delete_kb(doc["kb_name"], tenant_id, doc.get("userid", doc.get("user_id", "")))
    except Exception:
        logger.exception(f"KB deletion failed for {doc['kb_name']}")

    await coll.delete_one({"_id": doc["_id"]})

    # Clean up chat queries
    try:
        result = await get_db()[CHAT_QUERIES_COLLECTION].delete_many({"presentation_id": presentation_id})
        if result.deleted_count:
            logger.info(f"Deleted {result.deleted_count} chat queries for presentation {presentation_id}")
    except Exception:
        logger.exception(f"Failed to delete chat queries for presentation {presentation_id}")

    logger.info(f"Deleted presentation {presentation_id} kb={doc['kb_name']}")
    return True


async def toggle_publish(presentation_id: str, tenant_id: str, base_url: str = "") -> PresentationResponse:
    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"_id": ObjectId(presentation_id), "tenant_id": tenant_id})
    if not doc:
        raise ValueError("Presentation not found")

    new_val = not doc.get("is_published", True)
    now = datetime.now(timezone.utc)
    await coll.update_one({"_id": doc["_id"]}, {"$set": {"is_published": new_val, "updated_at": now}})
    doc["is_published"] = new_val
    doc["updated_at"] = now
    return _doc_to_response(doc, base_url)


async def get_by_id(presentation_id: str, tenant_id: str, base_url: str = "") -> PresentationDetail | None:
    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"_id": ObjectId(presentation_id), "tenant_id": tenant_id}, {"header_logo": 0})
    if not doc:
        return None
    stats = await _chat_query_stats([presentation_id])
    return _doc_to_detail(doc, base_url, stats.get(presentation_id))


async def get_by_slug(slug: str) -> dict | None:
    coll = get_db()[COLLECTION]
    return await coll.find_one({"slug": slug})


async def list_by_tenant(tenant_id: str, base_url: str = "") -> list[PresentationResponse]:
    coll = get_db()[COLLECTION]
    docs = await coll.find({"tenant_id": tenant_id}, {"header_logo": 0}).sort("created_at", -1).to_list(500)
    pids = [str(d["_id"]) for d in docs]
    stats = await _chat_query_stats(pids)
    return [_doc_to_response(d, base_url, stats.get(str(d["_id"]))) for d in docs]


MAX_LOGO_SIZE = 1 * 1024 * 1024  # 1 MB
ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}


async def upload_logo(
    presentation_id: str, tenant_id: str, file_data: bytes, content_type: str, base_url: str = ""
) -> PresentationResponse:
    if content_type not in ALLOWED_LOGO_TYPES:
        raise ValueError(f"Unsupported image type: {content_type}")
    if len(file_data) > MAX_LOGO_SIZE:
        raise ValueError("Logo must be under 1 MB")

    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"_id": ObjectId(presentation_id), "tenant_id": tenant_id})
    if not doc:
        raise ValueError("Presentation not found")

    import base64
    logo_b64 = base64.b64encode(file_data).decode("ascii")
    now = datetime.now(timezone.utc)
    await coll.update_one(
        {"_id": doc["_id"]},
        {"$set": {
            "header_logo": logo_b64,
            "header_logo_content_type": content_type,
            "has_header_logo": True,
            "updated_at": now,
        }},
    )
    doc["has_header_logo"] = True
    doc["updated_at"] = now
    return _doc_to_response(doc, base_url)


async def delete_logo(presentation_id: str, tenant_id: str, base_url: str = "") -> PresentationResponse:
    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"_id": ObjectId(presentation_id), "tenant_id": tenant_id})
    if not doc:
        raise ValueError("Presentation not found")

    now = datetime.now(timezone.utc)
    await coll.update_one(
        {"_id": doc["_id"]},
        {
            "$unset": {"header_logo": "", "header_logo_content_type": ""},
            "$set": {"has_header_logo": False, "updated_at": now},
        },
    )
    doc["has_header_logo"] = False
    doc["updated_at"] = now
    return _doc_to_response(doc, base_url)


CHAT_QUERIES_COLLECTION = "content_chat_queries"


async def list_chat_queries(
    presentation_id: str, tenant_id: str, page: int = 1, page_size: int = 25,
) -> dict:
    """Return paginated chat queries for a presentation."""
    coll_p = get_db()[COLLECTION]
    doc = await coll_p.find_one(
        {"_id": ObjectId(presentation_id), "tenant_id": tenant_id}, {"_id": 1}
    )
    if not doc:
        raise ValueError("Presentation not found")

    coll = get_db()[CHAT_QUERIES_COLLECTION]
    filt = {"presentation_id": presentation_id}
    total = await coll.count_documents(filt)
    skip = (page - 1) * page_size
    cursor = coll.find(filt).sort("created_at", -1).skip(skip).limit(page_size)
    items = []
    async for q in cursor:
        items.append({
            "id": str(q["_id"]),
            "question": q.get("question", ""),
            "client_ip": q.get("client_ip", ""),
            "access_code": q.get("access_code"),
            "session_id": q.get("session_id", ""),
            "date": q.get("date", ""),
            "created_at": (q["created_at"].isoformat() + "Z") if isinstance(q.get("created_at"), datetime) else str(q.get("created_at", "")),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def delete_chat_query(query_id: str, presentation_id: str, tenant_id: str) -> bool:
    """Delete a single chat query (after verifying ownership)."""
    coll_p = get_db()[COLLECTION]
    doc = await coll_p.find_one(
        {"_id": ObjectId(presentation_id), "tenant_id": tenant_id}, {"_id": 1}
    )
    if not doc:
        raise ValueError("Presentation not found")
    coll = get_db()[CHAT_QUERIES_COLLECTION]
    result = await coll.delete_one({"_id": ObjectId(query_id), "presentation_id": presentation_id})
    return result.deleted_count > 0


async def delete_all_chat_queries(presentation_id: str, tenant_id: str) -> int:
    """Delete all chat queries for a presentation."""
    coll_p = get_db()[COLLECTION]
    doc = await coll_p.find_one(
        {"_id": ObjectId(presentation_id), "tenant_id": tenant_id}, {"_id": 1}
    )
    if not doc:
        raise ValueError("Presentation not found")
    coll = get_db()[CHAT_QUERIES_COLLECTION]
    result = await coll.delete_many({"presentation_id": presentation_id})
    return result.deleted_count


async def get_logo(slug: str) -> tuple[bytes, str] | None:
    """Return (binary_data, content_type) or None."""
    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"slug": slug}, {"header_logo": 1, "header_logo_content_type": 1})
    if not doc or not doc.get("header_logo"):
        return None
    import base64
    return base64.b64decode(doc["header_logo"]), doc.get("header_logo_content_type", "image/png")

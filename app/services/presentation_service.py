"""
Presentation CRUD + KB lifecycle
"""
import logging
import secrets
import string
from datetime import datetime, timezone

from bson import ObjectId
from slugify import slugify

from app.db import get_db
from app.models.presentation import PresentationCreate, PresentationUpdate, PresentationResponse, PresentationDetail
from app.services import kb_service
from app.config import settings

logger = logging.getLogger(__name__)
COLLECTION = "content_presentations"


_CODE_CHARS = string.ascii_uppercase + string.digits  # A-Z, 0-9


def _generate_access_codes(count: int = 3) -> list[str]:
    """Generate unique 6-char alphanumeric access codes."""
    codes = set()
    while len(codes) < count:
        codes.add("".join(secrets.choice(_CODE_CHARS) for _ in range(6)))
    return sorted(codes)


def _kb_name(tenant_id: str, slug: str) -> str:
    return f"content_{tenant_id[:8]}_{slug}"


def _doc_to_response(doc: dict, base_url: str = "") -> PresentationResponse:
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
        description=doc.get("description"),
        tags=doc.get("tags", []),
        created_at=doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
        updated_at=doc["updated_at"].isoformat() if isinstance(doc["updated_at"], datetime) else str(doc["updated_at"]),
    )


def _doc_to_detail(doc: dict, base_url: str = "") -> PresentationDetail:
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
        description=doc.get("description"),
        tags=doc.get("tags", []),
        created_at=doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
        updated_at=doc["updated_at"].isoformat() if isinstance(doc["updated_at"], datetime) else str(doc["updated_at"]),
        markdown_content=doc.get("markdown_content", ""),
    )


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
        try:
            await kb_service.truncate_kb(doc["kb_name"], tenant_id, doc.get("userid", doc.get("user_id", "")))
            await kb_service.index_text(
                doc["kb_name"], data.markdown_content, tenant_id, doc.get("userid", doc.get("user_id", "")),
                display_file_name=data.title or doc["title"],
            )
        except Exception:
            logger.exception(f"KB re-index failed for {doc['kb_name']}")
            raise

    # Access protection
    if data.access_protected is not None:
        updates["access_protected"] = data.access_protected
        if data.access_protected and not doc.get("access_codes"):
            updates["access_codes"] = _generate_access_codes(3)
        elif not data.access_protected:
            updates["access_codes"] = []

    if data.regenerate_codes is not None and data.regenerate_codes > 0:
        updates["access_codes"] = _generate_access_codes(data.regenerate_codes)
        updates["access_protected"] = True

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
    doc = await coll.find_one({"_id": ObjectId(presentation_id), "tenant_id": tenant_id})
    return _doc_to_detail(doc, base_url) if doc else None


async def get_by_slug(slug: str) -> dict | None:
    coll = get_db()[COLLECTION]
    return await coll.find_one({"slug": slug})


async def list_by_tenant(tenant_id: str, base_url: str = "") -> list[PresentationResponse]:
    coll = get_db()[COLLECTION]
    docs = await coll.find({"tenant_id": tenant_id}).sort("created_at", -1).to_list(500)
    return [_doc_to_response(d, base_url) for d in docs]

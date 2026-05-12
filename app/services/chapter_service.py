"""
Chapter CRUD for multi-chapter "book" presentations.

Chapters are stored as an array on the parent presentation document
under the `chapters` field. Each chapter is identified by an ObjectId
in `chapter_id`.

This module does NOT trigger KB re-indexing — callers should mark
chapters with `indexed_at=None` on content change and let the
re-indexing slice (slice 3) pick them up.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from slugify import slugify

from app.db import get_db
from app.models.presentation import (
    ChapterCreate,
    ChapterDetail,
    ChapterResponse,
    ChapterUpdate,
)
from app.services.html_converter import _fallback_strip_tags, html_to_markdown
from app.services.md_renderer import render_markdown

logger = logging.getLogger(__name__)

COLLECTION = "content_presentations"


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _unique_chapter_slug(base: str, existing_slugs: set[str]) -> str:
    """Return a slug not already in existing_slugs."""
    slug = base or "chapter"
    if slug not in existing_slugs:
        return slug
    while True:
        candidate = f"{slug}-{secrets.token_hex(2)}"
        if candidate not in existing_slugs:
            return candidate


def _render_chapter_content(
    content_type: str,
    markdown_content: str | None,
    html_content: str | None,
    *,
    chapter_label: str,
) -> tuple[str, str, str]:
    """Return (content_type, markdown_to_store, html_to_store, hash_source).

    For markdown chapters: render html from markdown, hash the markdown.
    For html chapters: convert html -> markdown for KB, keep html as-is,
    hash the html.

    Raises ValueError if the chapter has no usable content.
    """
    content_type = content_type or "markdown"

    if content_type == "html":
        if not html_content or not html_content.strip():
            raise ValueError(f"Chapter '{chapter_label}': HTML content is required")
        kb_md = html_to_markdown(html_content)
        if not kb_md.strip():
            logger.warning(
                "Chapter '%s': html_to_markdown returned empty, using stripped text fallback",
                chapter_label,
            )
            kb_md = _fallback_strip_tags(html_content)
        return content_type, kb_md, html_content, html_content

    # markdown
    md = markdown_content or ""
    if not md.strip():
        raise ValueError(f"Chapter '{chapter_label}': content cannot be empty")
    rendered = render_markdown(md)
    return "markdown", md, rendered, md


def _build_chapter_doc(
    data: ChapterCreate,
    *,
    order: int,
    existing_slugs: set[str],
) -> dict:
    content_type, md_text, html_text, hash_source = _render_chapter_content(
        data.content_type,
        data.markdown_content,
        data.html_content,
        chapter_label=data.title,
    )
    base_slug = slugify(data.slug or data.title) or "chapter"
    slug = _unique_chapter_slug(base_slug, existing_slugs)

    return {
        "chapter_id": ObjectId(),
        "order": order,
        "title": data.title.strip(),
        "slug": slug,
        "section": data.section,
        "content_type": content_type,
        "markdown_content": md_text,
        "html_content": html_text,
        "content_hash": _content_hash(hash_source),
        "indexed_at": None,
    }


def _chapter_to_response(chapter: dict) -> ChapterResponse:
    return ChapterResponse(
        chapter_id=str(chapter["chapter_id"]),
        order=int(chapter.get("order", 0)),
        title=chapter.get("title", ""),
        slug=chapter.get("slug", ""),
        section=chapter.get("section"),
        content_type=chapter.get("content_type", "markdown"),
        indexed_at=chapter.get("indexed_at"),
    )


def _chapter_to_detail(chapter: dict) -> ChapterDetail:
    return ChapterDetail(
        chapter_id=str(chapter["chapter_id"]),
        order=int(chapter.get("order", 0)),
        title=chapter.get("title", ""),
        slug=chapter.get("slug", ""),
        section=chapter.get("section"),
        content_type=chapter.get("content_type", "markdown"),
        indexed_at=chapter.get("indexed_at"),
        markdown_content=chapter.get("markdown_content", ""),
        html_content=chapter.get("html_content"),
        content_hash=chapter.get("content_hash", ""),
    )


async def _load_presentation(presentation_id: str, tenant_id: str) -> dict:
    """Load a presentation, raising ValueError if absent."""
    try:
        oid = ObjectId(presentation_id)
    except (InvalidId, TypeError) as exc:
        raise ValueError(f"Invalid presentation id: {presentation_id}") from exc

    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"_id": oid, "tenant_id": tenant_id})
    if not doc:
        raise ValueError("Presentation not found")
    return doc


def _find_chapter(doc: dict, chapter_id: str) -> tuple[int, dict]:
    """Return (index, chapter_dict) for chapter_id in doc, or raise ValueError."""
    try:
        target = ObjectId(chapter_id)
    except (InvalidId, TypeError) as exc:
        raise ValueError(f"Invalid chapter id: {chapter_id}") from exc

    for idx, ch in enumerate(doc.get("chapters") or []):
        if ch.get("chapter_id") == target:
            return idx, ch
    raise ValueError("Chapter not found")


async def list_chapters(presentation_id: str, tenant_id: str) -> list[ChapterResponse]:
    doc = await _load_presentation(presentation_id, tenant_id)
    chapters = sorted(doc.get("chapters") or [], key=lambda c: c.get("order", 0))
    return [_chapter_to_response(c) for c in chapters]


async def get_chapter(
    presentation_id: str, chapter_id: str, tenant_id: str
) -> ChapterDetail:
    doc = await _load_presentation(presentation_id, tenant_id)
    _, chapter = _find_chapter(doc, chapter_id)
    return _chapter_to_detail(chapter)


async def add_chapter(
    presentation_id: str, tenant_id: str, data: ChapterCreate
) -> ChapterDetail:
    doc = await _load_presentation(presentation_id, tenant_id)

    existing = list(doc.get("chapters") or [])
    existing_slugs = {c.get("slug") for c in existing if c.get("slug")}

    if data.order is None:
        order = max((c.get("order", 0) for c in existing), default=-1) + 1
    else:
        order = int(data.order)

    chapter = _build_chapter_doc(data, order=order, existing_slugs=existing_slugs)

    now = datetime.now(timezone.utc)
    coll = get_db()[COLLECTION]
    result = await coll.update_one(
        {"_id": doc["_id"], "tenant_id": tenant_id},
        {
            "$push": {"chapters": chapter},
            "$set": {"updated_at": now, "layout": doc.get("layout", "single")},
        },
    )
    if result.modified_count != 1:
        # Race condition or missing doc — re-check
        logger.warning(
            "add_chapter modified_count=%s for presentation=%s",
            result.modified_count,
            presentation_id,
        )
        raise ValueError("Failed to add chapter — presentation may have been deleted")

    logger.info(
        "Added chapter '%s' (slug=%s, order=%s) to presentation %s",
        chapter["title"],
        chapter["slug"],
        order,
        presentation_id,
    )
    return _chapter_to_detail(chapter)


async def update_chapter(
    presentation_id: str,
    chapter_id: str,
    tenant_id: str,
    data: ChapterUpdate,
) -> ChapterDetail:
    doc = await _load_presentation(presentation_id, tenant_id)
    idx, existing = _find_chapter(doc, chapter_id)

    new_chapter = dict(existing)  # copy
    content_changed = False

    if data.title is not None:
        new_chapter["title"] = data.title.strip()

    if data.section is not None:
        new_chapter["section"] = data.section

    if data.order is not None:
        new_chapter["order"] = int(data.order)

    # Slug change must remain unique within presentation
    if data.slug is not None:
        base = slugify(data.slug) or "chapter"
        siblings = {
            c.get("slug")
            for i, c in enumerate(doc.get("chapters") or [])
            if i != idx and c.get("slug")
        }
        new_chapter["slug"] = _unique_chapter_slug(base, siblings)

    # Content / type
    type_changing = data.content_type is not None and data.content_type != existing.get(
        "content_type", "markdown"
    )
    md_changing = (
        data.markdown_content is not None
        and data.markdown_content != existing.get("markdown_content")
    )
    html_changing = (
        data.html_content is not None
        and data.html_content != existing.get("html_content")
    )

    if type_changing or md_changing or html_changing:
        content_type = data.content_type or existing.get("content_type", "markdown")
        md_in = (
            data.markdown_content
            if data.markdown_content is not None
            else existing.get("markdown_content", "")
        )
        html_in = (
            data.html_content
            if data.html_content is not None
            else existing.get("html_content")
        )
        ct, md_out, html_out, hash_source = _render_chapter_content(
            content_type,
            md_in,
            html_in,
            chapter_label=new_chapter["title"],
        )
        new_chapter["content_type"] = ct
        new_chapter["markdown_content"] = md_out
        new_chapter["html_content"] = html_out
        new_chapter["content_hash"] = _content_hash(hash_source)
        new_chapter["indexed_at"] = None
        content_changed = True

    if new_chapter == existing:
        return _chapter_to_detail(existing)

    now = datetime.now(timezone.utc)
    coll = get_db()[COLLECTION]
    result = await coll.update_one(
        {
            "_id": doc["_id"],
            "tenant_id": tenant_id,
            "chapters.chapter_id": existing["chapter_id"],
        },
        {
            "$set": {
                "chapters.$": new_chapter,
                "updated_at": now,
            }
        },
    )
    if result.matched_count != 1:
        logger.warning(
            "update_chapter matched_count=%s for presentation=%s chapter=%s",
            result.matched_count,
            presentation_id,
            chapter_id,
        )
        raise ValueError("Chapter update failed — record may have been modified")

    logger.info(
        "Updated chapter %s (title=%s, content_changed=%s) on presentation %s",
        chapter_id,
        new_chapter["title"],
        content_changed,
        presentation_id,
    )
    return _chapter_to_detail(new_chapter)


async def delete_chapter(
    presentation_id: str, chapter_id: str, tenant_id: str
) -> bool:
    doc = await _load_presentation(presentation_id, tenant_id)
    _, existing = _find_chapter(doc, chapter_id)

    if len(doc.get("chapters") or []) <= 1:
        raise ValueError("Cannot delete the last chapter — a presentation must have at least one chapter")

    now = datetime.now(timezone.utc)
    coll = get_db()[COLLECTION]
    result = await coll.update_one(
        {"_id": doc["_id"], "tenant_id": tenant_id},
        {
            "$pull": {"chapters": {"chapter_id": existing["chapter_id"]}},
            "$set": {"updated_at": now},
        },
    )
    if result.modified_count != 1:
        logger.warning(
            "delete_chapter modified_count=%s for presentation=%s chapter=%s",
            result.modified_count,
            presentation_id,
            chapter_id,
        )
        raise ValueError("Chapter delete failed — record may have been modified")

    logger.info("Deleted chapter %s from presentation %s", chapter_id, presentation_id)
    return True


async def reorder_chapters(
    presentation_id: str, tenant_id: str, ordered_chapter_ids: list[str]
) -> list[ChapterResponse]:
    doc = await _load_presentation(presentation_id, tenant_id)
    chapters = list(doc.get("chapters") or [])

    if len(ordered_chapter_ids) != len(chapters):
        raise ValueError(
            f"Reorder requires all {len(chapters)} chapter ids; "
            f"got {len(ordered_chapter_ids)}"
        )

    try:
        ordered_oids = [ObjectId(cid) for cid in ordered_chapter_ids]
    except (InvalidId, TypeError) as exc:
        raise ValueError(f"Invalid chapter id in reorder list: {exc}") from exc

    existing_ids = {c["chapter_id"] for c in chapters}
    if set(ordered_oids) != existing_ids:
        raise ValueError("Reorder list must contain exactly the existing chapter ids")

    by_id = {c["chapter_id"]: c for c in chapters}
    new_chapters = []
    for new_order, oid in enumerate(ordered_oids):
        ch = dict(by_id[oid])
        ch["order"] = new_order
        new_chapters.append(ch)

    now = datetime.now(timezone.utc)
    coll = get_db()[COLLECTION]
    await coll.update_one(
        {"_id": doc["_id"], "tenant_id": tenant_id},
        {"$set": {"chapters": new_chapters, "updated_at": now}},
    )
    logger.info(
        "Reordered %d chapters on presentation %s", len(new_chapters), presentation_id
    )
    return [_chapter_to_response(c) for c in new_chapters]

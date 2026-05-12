"""
Public page serving — no auth required
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.db import get_db
from app.services import presentation_service
from app.services.md_renderer import render_markdown

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class AccessCodeRequest(BaseModel):
    code: str


def _build_theme_and_header(doc: dict, slug: str) -> dict:
    header = doc.get("header") or {}
    has_logo = doc.get("has_header_logo", False)
    theme = doc.get("theme") or {}
    return {
        "header_enabled": header.get("enabled", False),
        "header_logo_url": f"/p/{slug}/logo" if has_logo else "",
        "header_link_url": header.get("link_url") or "",
        "header_link_text": header.get("link_text") or "",
        "header_email": header.get("email") or "",
        "header_phone": header.get("phone") or "",
        "header_text": header.get("text") or "",
        "theme_primary_color": theme.get("primary_color", "#2563eb"),
        "theme_secondary_color": theme.get("secondary_color", "#4f46e5"),
        "theme_accent_color": theme.get("accent_color", "#f59e0b"),
        "theme_font_family": theme.get("font_family", "System Default"),
        "theme_dark_mode": theme.get("dark_mode", False),
        "theme_custom_css": theme.get("custom_css", ""),
    }


async def _track_view(doc: dict, request: Request, slug: str) -> None:
    """Increment num_views and record last-view metadata. Best-effort."""
    client_ip = request.client.host if request.client else "unknown"
    access_code = request.cookies.get(f"cp_access_{slug}")
    try:
        coll = get_db()["content_presentations"]
        view_set: dict = {
            "last_view_date": datetime.now(timezone.utc).isoformat(),
            "last_view_ip": client_ip,
        }
        if access_code:
            view_set["last_view_access_code"] = access_code
        await coll.update_one(
            {"_id": doc["_id"]},
            {"$inc": {"num_views": 1}, "$set": view_set},
        )
    except Exception as exc:
        logger.warning("Failed to track page view for slug=%s: %s", slug, exc)


def _is_access_blocked(doc: dict, request: Request, slug: str) -> bool:
    if not (doc.get("access_protected") and doc.get("access_codes")):
        return False
    verified_code = request.cookies.get(f"cp_access_{slug}")
    return not verified_code or verified_code not in doc["access_codes"]


def _normalize_book_chapters(doc: dict) -> list[dict]:
    """Return chapters sorted by `order`, with pre-rendered HTML."""
    chapters = sorted(
        list(doc.get("chapters") or []), key=lambda c: c.get("order", 0)
    )
    normalized: list[dict] = []
    for ch in chapters:
        html = ch.get("html_content")
        if not html:
            html = render_markdown(ch.get("markdown_content") or "")
        normalized.append(
            {
                "chapter_id": str(ch.get("chapter_id")),
                "title": ch.get("title", "Untitled"),
                "slug": ch.get("slug", ""),
                "section": ch.get("section"),
                "order": int(ch.get("order", 0)),
                "html": html or "",
            }
        )
    return normalized


def _render_single_page(
    request: Request, doc: dict, slug: str
) -> HTMLResponse:
    content_type = doc.get("content_type", "markdown")
    if content_type == "html" and doc.get("html_content"):
        html_content = doc["html_content"]
    else:
        html_content = render_markdown(doc.get("markdown_content", ""))

    ctx = {
        "title": doc["title"],
        "description": doc.get("description") or "",
        "content_type": content_type,
        "html_content": html_content,
        "presentation_id": str(doc["_id"]),
        "chat_enabled": "true" if doc.get("chat_enabled", True) else "false",
        "api_base": "",
    }
    ctx.update(_build_theme_and_header(doc, slug))
    return templates.TemplateResponse(request, "page.html", ctx)


def _render_book(
    request: Request, doc: dict, slug: str, chapter_slug: str | None
) -> HTMLResponse:
    chapters = _normalize_book_chapters(doc)
    if not chapters:
        # No chapters — fall back to single-page render so the page
        # isn't an empty shell.
        logger.warning(
            "Presentation %s has layout=book but no chapters; falling back to single",
            doc.get("slug"),
        )
        return _render_single_page(request, doc, slug)

    # Resolve which chapter to show. Default = first.
    selected = chapters[0]
    if chapter_slug:
        match = next((c for c in chapters if c["slug"] == chapter_slug), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Chapter not found")
        selected = match

    ctx = {
        "title": doc["title"],
        "description": doc.get("description") or "",
        "presentation_id": str(doc["_id"]),
        "chat_enabled": "true" if doc.get("chat_enabled", True) else "false",
        "api_base": "",
        "slug": slug,
        "chapters": chapters,
        "selected_chapter_slug": selected["slug"],
        "selected_chapter_title": selected["title"],
        "selected_chapter_html": selected["html"],
    }
    ctx.update(_build_theme_and_header(doc, slug))
    return templates.TemplateResponse(request, "book.html", ctx)


async def _serve_presentation(
    request: Request, slug: str, chapter_slug: str | None = None
) -> HTMLResponse:
    doc = await presentation_service.get_by_slug(slug)
    if not doc or not doc.get("is_published", True):
        raise HTTPException(status_code=404, detail="Page not found")

    if _is_access_blocked(doc, request, slug):
        return templates.TemplateResponse(
            request,
            "access_code.html",
            {"title": doc["title"], "slug": slug},
        )

    await _track_view(doc, request, slug)

    if doc.get("layout") == "book":
        return _render_book(request, doc, slug, chapter_slug)
    return _render_single_page(request, doc, slug)


@router.get("/p/{slug}", response_class=HTMLResponse)
async def serve_page(slug: str, request: Request):
    return await _serve_presentation(request, slug)


@router.get("/p/{slug}/c/{chapter_slug}", response_class=HTMLResponse)
async def serve_chapter(slug: str, chapter_slug: str, request: Request):
    return await _serve_presentation(request, slug, chapter_slug)


@router.get("/p/{slug}/logo")
async def serve_logo(slug: str):
    result = await presentation_service.get_logo(slug)
    if not result:
        raise HTTPException(status_code=404, detail="No logo found")
    data, content_type = result
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})


@router.post("/p/{slug}/verify")
async def verify_access_code(slug: str, data: AccessCodeRequest):
    doc = await presentation_service.get_by_slug(slug)
    if not doc:
        raise HTTPException(status_code=404, detail="Page not found")

    code = data.code.strip().upper()
    if code not in doc.get("access_codes", []):
        raise HTTPException(status_code=403, detail="Invalid access code")

    return {"verified": True, "code": code}

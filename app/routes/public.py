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


@router.get("/p/{slug}", response_class=HTMLResponse)
async def serve_page(slug: str, request: Request):
    doc = await presentation_service.get_by_slug(slug)
    if not doc or not doc.get("is_published", True):
        raise HTTPException(status_code=404, detail="Page not found")

    # Check access protection
    if doc.get("access_protected") and doc.get("access_codes"):
        # Check cookie for prior verification
        cookie_key = f"cp_access_{slug}"
        verified_code = request.cookies.get(cookie_key)
        if not verified_code or verified_code not in doc["access_codes"]:
            return templates.TemplateResponse(
                "access_code.html",
                {
                    "request": request,
                    "title": doc["title"],
                    "slug": slug,
                },
            )

    # Track page view (fire-and-forget)
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

    content_type = doc.get("content_type", "markdown")

    if content_type == "html" and doc.get("html_content"):
        html_content = doc["html_content"]
    else:
        html_content = render_markdown(doc.get("markdown_content", ""))

    # Build header context
    header = doc.get("header") or {}
    header_enabled = header.get("enabled", False)
    has_logo = doc.get("has_header_logo", False)

    # Build theme context
    theme = doc.get("theme") or {}

    return templates.TemplateResponse(
        "page.html",
        {
            "request": request,
            "title": doc["title"],
            "description": doc.get("description") or "",
            "content_type": content_type,
            "html_content": html_content,
            "presentation_id": str(doc["_id"]),
            "chat_enabled": "true" if doc.get("chat_enabled", True) else "false",
            "api_base": "",
            "header_enabled": header_enabled,
            "header_logo_url": f"/p/{slug}/logo" if has_logo else "",
            "header_link_url": header.get("link_url") or "",
            "header_link_text": header.get("link_text") or "",
            "header_email": header.get("email") or "",
            "header_phone": header.get("phone") or "",
            "header_text": header.get("text") or "",
            # Theme
            "theme_primary_color": theme.get("primary_color", "#2563eb"),
            "theme_secondary_color": theme.get("secondary_color", "#4f46e5"),
            "theme_accent_color": theme.get("accent_color", "#f59e0b"),
            "theme_font_family": theme.get("font_family", "System Default"),
            "theme_dark_mode": theme.get("dark_mode", False),
            "theme_custom_css": theme.get("custom_css", ""),
        },
    )


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

"""
Public page serving — no auth required
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.services import presentation_service
from app.services.md_renderer import render_markdown

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

    html_content = render_markdown(doc["markdown_content"])
    api_base = str(request.base_url).rstrip("/")

    return templates.TemplateResponse(
        "page.html",
        {
            "request": request,
            "title": doc["title"],
            "description": doc.get("description") or "",
            "html_content": html_content,
            "presentation_id": str(doc["_id"]),
            "chat_enabled": "true" if doc.get("chat_enabled", True) else "false",
            "api_base": api_base,
        },
    )


@router.post("/p/{slug}/verify")
async def verify_access_code(slug: str, data: AccessCodeRequest):
    doc = await presentation_service.get_by_slug(slug)
    if not doc:
        raise HTTPException(status_code=404, detail="Page not found")

    code = data.code.strip().upper()
    if code not in doc.get("access_codes", []):
        raise HTTPException(status_code=403, detail="Invalid access code")

    return {"verified": True, "code": code}

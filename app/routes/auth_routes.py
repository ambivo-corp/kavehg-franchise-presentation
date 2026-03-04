"""
Login page + login API proxy to ambivo_api /user/login
"""
import logging
from typing import Dict, Any

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class LoginRequest(BaseModel):
    email: str
    password: str
    device_id: str | None = None
    os: str = "web"


@router.get("/", response_class=HTMLResponse)
async def root_redirect(request: Request):
    """Redirect to dashboard or login based on client-side auth check."""
    return HTMLResponse(
        '<script>'
        'if(localStorage.getItem("cp_token")){window.location.replace("/dashboard")}'
        'else{window.location.replace("/login")}'
        '</script>'
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "api_base": "",
    })


@router.get("/dashboard/create", response_class=HTMLResponse)
async def create_page(request: Request):
    return templates.TemplateResponse("create.html", {
        "request": request,
        "api_base": "",
    })


@router.get("/dashboard/edit/{presentation_id}", response_class=HTMLResponse)
async def edit_page(request: Request, presentation_id: str):
    return templates.TemplateResponse("edit.html", {
        "request": request,
        "api_base": "",
        "presentation_id": presentation_id,
    })


@router.post("/api/auth/login")
async def login_api(data: LoginRequest) -> Dict[str, Any]:
    """Proxy login to ambivo_api /user/login, return token."""
    try:
        payload = {
            "email": data.email,
            "password": data.password,
            "os": data.os,
        }
        if data.device_id:
            payload["device_id"] = data.device_id

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.ambivo_api_url}/user/login",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            result = resp.json()
    except Exception as e:
        logger.exception("Login proxy error")
        raise HTTPException(status_code=502, detail="Unable to reach authentication service")

    if result.get("result") != 1:
        raise HTTPException(
            status_code=401,
            detail=result.get("error", {}).get("message") or result.get("error_code") or "Login failed",
        )

    user = result.get("user", {})
    return {
        "result": 1,
        "token": user.get("token"),
        "user": {
            "id": user.get("id"),
            "name": user.get("name") or user.get("formatted_name") or user.get("email"),
            "email": user.get("email"),
            "tenant_id": user.get("tenant_id"),
        },
    }

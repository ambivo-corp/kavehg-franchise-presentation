"""
Pydantic models for presentations
"""
from typing import Literal

from pydantic import BaseModel


class HeaderConfig(BaseModel):
    enabled: bool = False
    logo_url: str | None = None  # served via /p/{slug}/logo
    link_url: str | None = None
    link_text: str | None = None
    email: str | None = None
    phone: str | None = None
    text: str | None = None


class HeaderUpdate(BaseModel):
    enabled: bool | None = None
    link_url: str | None = None
    link_text: str | None = None
    email: str | None = None
    phone: str | None = None
    text: str | None = None


class PresentationCreate(BaseModel):
    title: str
    markdown_content: str = ""
    html_content: str | None = None
    content_type: Literal["markdown", "html"] = "markdown"
    slug: str | None = None
    description: str | None = None
    tags: list[str] = []
    chat_enabled: bool = True
    access_protected: bool = False
    num_access_codes: int = 3
    header: HeaderUpdate | None = None


class PresentationUpdate(BaseModel):
    title: str | None = None
    markdown_content: str | None = None
    html_content: str | None = None
    content_type: Literal["markdown", "html"] | None = None
    description: str | None = None
    tags: list[str] | None = None
    chat_enabled: bool | None = None
    access_protected: bool | None = None
    access_codes: list[str] | None = None
    regenerate_codes: int | None = None
    header: HeaderUpdate | None = None


class PresentationResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    slug: str
    hosted_url: str
    kb_name: str
    content_type: str = "markdown"  # "markdown" or "html"
    is_published: bool
    chat_enabled: bool
    access_protected: bool = False
    access_codes: list[str] = []
    header: HeaderConfig = HeaderConfig()
    description: str | None = None
    tags: list[str] = []
    created_at: str
    updated_at: str
    # Stats
    num_views: int = 0
    total_chat_queries: int = 0
    today_chat_queries: int = 0


class PresentationDetail(PresentationResponse):
    markdown_content: str
    html_content: str | None = None


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None

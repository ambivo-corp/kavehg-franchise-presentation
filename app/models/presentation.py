"""
Pydantic models for presentations
"""
from pydantic import BaseModel


class PresentationCreate(BaseModel):
    title: str
    markdown_content: str
    slug: str | None = None
    description: str | None = None
    tags: list[str] = []
    chat_enabled: bool = True
    access_protected: bool = False
    num_access_codes: int = 3


class PresentationUpdate(BaseModel):
    title: str | None = None
    markdown_content: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    chat_enabled: bool | None = None
    access_protected: bool | None = None
    regenerate_codes: int | None = None


class PresentationResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    slug: str
    hosted_url: str
    kb_name: str
    is_published: bool
    chat_enabled: bool
    access_protected: bool = False
    access_codes: list[str] = []
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


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None

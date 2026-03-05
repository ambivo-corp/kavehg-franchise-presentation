"""
Authenticated CRUD routes for presentations
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from typing import Dict, Any

from app.auth.jwt_auth import get_current_user
from app.models.presentation import PresentationCreate, PresentationUpdate, PresentationResponse, PresentationDetail
from app.services import presentation_service

router = APIRouter(prefix="/api/presentations", tags=["presentations"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.post("", response_model=PresentationResponse, status_code=201)
async def create_presentation(
    data: PresentationCreate,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return await presentation_service.create(
            user["tenant_id"], user["userid"], data, _base_url(request)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=list[PresentationResponse])
async def list_presentations(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    return await presentation_service.list_by_tenant(user["tenant_id"], _base_url(request))


@router.get("/{presentation_id}", response_model=PresentationDetail)
async def get_presentation(
    presentation_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    result = await presentation_service.get_by_id(presentation_id, user["tenant_id"], _base_url(request))
    if not result:
        raise HTTPException(status_code=404, detail="Presentation not found")
    return result


@router.put("/{presentation_id}", response_model=PresentationResponse)
async def update_presentation(
    presentation_id: str,
    data: PresentationUpdate,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return await presentation_service.update(
            presentation_id, user["tenant_id"], data, _base_url(request)
        )
    except ValueError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{presentation_id}", status_code=204)
async def delete_presentation(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        await presentation_service.delete(presentation_id, user["tenant_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{presentation_id}/publish", response_model=PresentationResponse)
async def toggle_publish(
    presentation_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return await presentation_service.toggle_publish(
            presentation_id, user["tenant_id"], _base_url(request)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{presentation_id}/queries")
async def list_chat_queries(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    page: int = 1,
    page_size: int = 25,
):
    try:
        return await presentation_service.list_chat_queries(
            presentation_id, user["tenant_id"], page, page_size
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{presentation_id}/queries/{query_id}", status_code=204)
async def delete_chat_query(
    presentation_id: str,
    query_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        await presentation_service.delete_chat_query(query_id, presentation_id, user["tenant_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{presentation_id}/queries", status_code=204)
async def delete_all_chat_queries(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        await presentation_service.delete_all_chat_queries(presentation_id, user["tenant_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{presentation_id}/logo", response_model=PresentationResponse)
async def upload_logo(
    presentation_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        file_data = await file.read()
        return await presentation_service.upload_logo(
            presentation_id, user["tenant_id"], file_data, file.content_type or "image/png", _base_url(request)
        )
    except ValueError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.delete("/{presentation_id}/logo", response_model=PresentationResponse)
async def delete_logo(
    presentation_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return await presentation_service.delete_logo(
            presentation_id, user["tenant_id"], _base_url(request)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

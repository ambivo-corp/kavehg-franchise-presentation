"""
Authenticated CRUD routes for presentations
"""
import logging

from bson.errors import InvalidId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel
from typing import Dict, Any

from app.auth.jwt_auth import get_current_user
from app.models.presentation import (
    ChapterCreate,
    ChapterDetail,
    ChapterResponse,
    ChapterUpdate,
    PresentationCreate,
    PresentationDetail,
    PresentationResponse,
    PresentationUpdate,
)
from app.services import chapter_service, document_converter, kb_service, presentation_service
from app.services.document_converter import (
    ConversionError,
    FileTooLargeError,
    UnsupportedFormatError,
)

logger = logging.getLogger(__name__)

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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Failed to create presentation")
        raise HTTPException(status_code=500, detail="Internal server error")


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
    try:
        result = await presentation_service.get_by_id(presentation_id, user["tenant_id"], _base_url(request))
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid presentation ID format")
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
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid presentation ID format")
    except ValueError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))
    except Exception:
        logger.exception("Failed to update presentation %s", presentation_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{presentation_id}", status_code=204)
async def delete_presentation(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        await presentation_service.delete(presentation_id, user["tenant_id"])
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid presentation ID format")
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
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid presentation ID format")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{presentation_id}/queries")
async def list_chat_queries(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    try:
        return await presentation_service.list_chat_queries(
            presentation_id, user["tenant_id"], page, page_size
        )
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ID format")
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
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{presentation_id}/queries", status_code=204)
async def delete_all_chat_queries(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        await presentation_service.delete_all_chat_queries(presentation_id, user["tenant_id"])
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ID format")
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
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid presentation ID format")
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
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid presentation ID format")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Chapter CRUD (book mode)
# ---------------------------------------------------------------------------


def _chapter_value_status(detail: str) -> int:
    """Map ValueError detail to an HTTP status code for chapter routes."""
    lower = detail.lower()
    if "not found" in lower:
        return 404
    return 400


@router.get(
    "/{presentation_id}/chapters",
    response_model=list[ChapterResponse],
)
async def list_chapters(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return await chapter_service.list_chapters(presentation_id, user["tenant_id"])
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception("Failed to list chapters for presentation %s", presentation_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{presentation_id}/chapters",
    response_model=ChapterDetail,
    status_code=201,
)
async def add_chapter(
    presentation_id: str,
    data: ChapterCreate,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        result = await chapter_service.add_chapter(
            presentation_id, user["tenant_id"], data
        )
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception("Failed to add chapter to presentation %s", presentation_id)
        raise HTTPException(status_code=500, detail="Internal server error")

    background_tasks.add_task(
        chapter_service.reindex_presentation,
        presentation_id,
        user["tenant_id"],
        user["userid"],
    )
    return result


@router.get(
    "/{presentation_id}/chapters/{chapter_id}",
    response_model=ChapterDetail,
)
async def get_chapter(
    presentation_id: str,
    chapter_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return await chapter_service.get_chapter(
            presentation_id, chapter_id, user["tenant_id"]
        )
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception(
            "Failed to get chapter %s on presentation %s", chapter_id, presentation_id
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{presentation_id}/chapters/{chapter_id}",
    response_model=ChapterDetail,
)
async def update_chapter(
    presentation_id: str,
    chapter_id: str,
    data: ChapterUpdate,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        result = await chapter_service.update_chapter(
            presentation_id, chapter_id, user["tenant_id"], data
        )
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception(
            "Failed to update chapter %s on presentation %s", chapter_id, presentation_id
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    # Only reindex when content fields changed; metadata-only edits skip.
    content_touched = any(
        getattr(data, f) is not None
        for f in ("content_type", "markdown_content", "html_content")
    )
    if content_touched:
        background_tasks.add_task(
            chapter_service.reindex_presentation,
            presentation_id,
            user["tenant_id"],
            user["userid"],
        )
    return result


@router.delete(
    "/{presentation_id}/chapters/{chapter_id}",
    status_code=204,
)
async def delete_chapter(
    presentation_id: str,
    chapter_id: str,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        await chapter_service.delete_chapter(
            presentation_id, chapter_id, user["tenant_id"]
        )
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception(
            "Failed to delete chapter %s on presentation %s", chapter_id, presentation_id
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    background_tasks.add_task(
        chapter_service.reindex_presentation,
        presentation_id,
        user["tenant_id"],
        user["userid"],
    )


class ReorderRequest(BaseModel):
    chapter_ids: list[str]


@router.put(
    "/{presentation_id}/chapters/reorder",
    response_model=list[ChapterResponse],
)
async def reorder_chapters(
    presentation_id: str,
    data: ReorderRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return await chapter_service.reorder_chapters(
            presentation_id, user["tenant_id"], data.chapter_ids
        )
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception(
            "Failed to reorder chapters on presentation %s", presentation_id
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{presentation_id}/chapters/upload",
    response_model=ChapterDetail,
    status_code=201,
)
async def upload_chapter(
    presentation_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    slug: str | None = Form(None),
    section: str | None = Form(None),
    order: int | None = Form(None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Create a chapter from an uploaded .md/.txt/.html/.pdf/.docx/.pptx file.

    The file is converted to markdown server-side via markitdown.
    If `title` is omitted, it's derived from the first H1 in the
    converted markdown or the filename stem.
    """
    try:
        file_bytes = await file.read()
    except Exception:
        logger.exception("Failed to read upload for presentation %s", presentation_id)
        raise HTTPException(status_code=400, detail="Could not read uploaded file")

    try:
        converted = await document_converter.convert_file(
            file_bytes, file.filename or ""
        )
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except ConversionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    chapter_data = ChapterCreate(
        title=(title or converted.suggested_title).strip(),
        slug=slug,
        section=section,
        order=order,
        content_type="markdown",
        markdown_content=converted.markdown,
    )

    try:
        result = await chapter_service.add_chapter(
            presentation_id, user["tenant_id"], chapter_data
        )
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception(
            "Failed to add uploaded chapter to presentation %s", presentation_id
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    background_tasks.add_task(
        chapter_service.reindex_presentation,
        presentation_id,
        user["tenant_id"],
        user["userid"],
    )
    return result


@router.post("/{presentation_id}/chapters/bulk-import")
async def bulk_import_chapters(
    presentation_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Bulk-create or update chapters from multiple uploaded files.

    Each file is converted via markitdown and matched against existing
    chapters by slug (derived from filename stem):
      - existing slug → update content + title in place
      - new slug → append as a new chapter

    Per-file conversion failures don't abort the batch — they're
    reported in `failed`. Triggers a single background reindex.
    """
    payload: list[tuple[str, bytes]] = []
    for uf in files:
        try:
            data = await uf.read()
        except Exception:
            logger.exception(
                "Failed to read uploaded file %s in bulk-import for %s",
                uf.filename,
                presentation_id,
            )
            continue
        payload.append((uf.filename or "unnamed", data))

    if not payload:
        raise HTTPException(status_code=400, detail="No files received")

    try:
        result = await chapter_service.bulk_import_chapters(
            presentation_id, user["tenant_id"], payload
        )
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))
    except Exception:
        logger.exception(
            "Bulk import failed for presentation %s", presentation_id
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    if result["created"] or result["updated"]:
        background_tasks.add_task(
            chapter_service.reindex_presentation,
            presentation_id,
            user["tenant_id"],
            user["userid"],
        )
    return result


def _extract_vector_size(details: dict) -> int | None:
    """Pull the unnamed-vector size out of a Qdrant collection dump.

    Mirrors QdrantService.get_collection_dim in ambivo-vectordb: handles
    both flat ({"size": N, "distance": ...}) and named-vector
    ({"<name>": {"size": N, ...}}) layouts. Returns None on any
    unparseable shape.
    """
    try:
        config = (details or {}).get("config") or {}
        params = config.get("params") or {}
        vectors = params.get("vectors") or {}
        if not isinstance(vectors, dict):
            return None
        size = vectors.get("size")
        if isinstance(size, int) and not isinstance(size, bool):
            return size
        default = vectors.get("")
        if default is None and vectors:
            default = next(iter(vectors.values()), None)
        if isinstance(default, dict):
            inner = default.get("size")
            if isinstance(inner, int) and not isinstance(inner, bool):
                return inner
    except (AttributeError, TypeError):
        return None
    return None


@router.get("/{presentation_id}/kb-info")
async def kb_info(
    presentation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Diagnostic: return VectorDB's current view of this presentation's
    KB collection — primarily the vector dimension it was created with,
    so we can confirm whether a force-recreate actually healed a stale
    collection or whether the collection is still pinned to the old dim.

    Tenant-scoped: validates the presentation belongs to the calling
    user's tenant before forwarding to VectorDB.
    """
    from bson import ObjectId
    from app.db import get_db

    try:
        oid = ObjectId(presentation_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid presentation id")

    doc = await get_db()["content_presentations"].find_one(
        {"_id": oid, "tenant_id": user["tenant_id"]},
        {"kb_name": 1, "slug": 1, "chapters": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Presentation not found")

    kb_name = doc.get("kb_name")
    if not kb_name:
        raise HTTPException(
            status_code=409, detail="Presentation has no kb_name"
        )

    try:
        envelope = await kb_service.get_kb_info(
            kb_name, user["tenant_id"], user["userid"]
        )
    except Exception as exc:
        logger.exception("kb_info: VectorDB call failed for kb=%s", kb_name)
        raise HTTPException(
            status_code=502,
            detail=f"VectorDB request failed: {type(exc).__name__}",
        )

    details = envelope.get("response") if isinstance(envelope, dict) else None
    vector_size = _extract_vector_size(details) if isinstance(details, dict) else None

    return {
        "presentation_id": presentation_id,
        "slug": doc.get("slug"),
        "kb_name": kb_name,
        "chapter_count": len(doc.get("chapters") or []),
        "vector_size": vector_size,
        "vectordb_envelope": envelope,
    }


@router.post(
    "/{presentation_id}/reindex",
    status_code=202,
)
async def trigger_reindex(
    presentation_id: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Delete + recreate the KB collection before reindexing. Use when embedding dimensions are stale."),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Manually schedule a KB re-index for this presentation.

    Returns 202 Accepted — the actual reindex runs in the background.

    Set `?force=true` to delete and recreate the KB collection (rather
    than truncate) — needed when the collection's embedding dimension
    is stale, e.g. when VectorDB switched embedding models since the
    collection was first created.
    """
    # Validate the presentation exists + belongs to tenant before scheduling.
    try:
        await chapter_service.list_chapters(presentation_id, user["tenant_id"])
    except ValueError as e:
        raise HTTPException(status_code=_chapter_value_status(str(e)), detail=str(e))

    background_tasks.add_task(
        chapter_service.reindex_presentation,
        presentation_id,
        user["tenant_id"],
        user["userid"],
        force_recreate=force,
    )
    return {
        "status": "scheduled",
        "presentation_id": presentation_id,
        "force_recreate": force,
    }

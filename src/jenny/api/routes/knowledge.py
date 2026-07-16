"""routes base de connaissances."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from jenny.api.dependencies import DbSession  # noqa: TC001
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.rag.knowledge_base import KnowledgeBase, KnowledgeEntry

logger = get_logger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


# schémas


class AddTextRequest(BaseModel):
    """requête ajout de texte."""

    business_id: UUID = Field(..., description="ID du business")
    title: str = Field("", description="Titre du document")
    content: str = Field(..., min_length=1, max_length=50000, description="Texte à mémoriser")
    category: str = Field(
        "general",
        description="Catégorie : horaires, tarifs, faq, politique, services, equipe, general",
    )


class KnowledgeEntryResponse(BaseModel):
    """détails d'une entrée."""

    id: str
    business_id: str
    title: str
    content_preview: str
    source: str
    category: str
    chunks_count: int
    created_at: str


class KnowledgeStatsResponse(BaseModel):
    """stats de la base."""

    business_id: str
    total_entries: int
    total_chunks: int
    by_category: dict[str, int]
    by_source: dict[str, int]


# helpers


def _enforce_tenant(request: Request, business_id: UUID) -> None:
    """vérifie le tenant."""
    settings = get_settings()
    if not settings.require_auth:
        return
    ctx_bid = getattr(request.state, "business_id", None)
    if ctx_bid is not None and str(ctx_bid) != str(business_id):
        raise HTTPException(status_code=403, detail="Accès refusé pour ce business")


def _to_response(entry: KnowledgeEntry) -> KnowledgeEntryResponse:
    preview = entry.content[:200] + "..." if len(entry.content) > 200 else entry.content
    return KnowledgeEntryResponse(
        id=entry.id,
        business_id=str(entry.business_id),
        title=entry.title,
        content_preview=preview,
        source=entry.source,
        category=entry.category,
        chunks_count=entry.chunks_count,
        created_at=entry.created_at.isoformat(),
    )


# routes


@router.post("/text", response_model=KnowledgeEntryResponse, status_code=201)
async def add_text(
    request: Request,
    body: AddTextRequest,
    db: DbSession,
) -> KnowledgeEntryResponse:
    """ajoute du texte."""
    _enforce_tenant(request, body.business_id)
    kb = KnowledgeBase(business_id=body.business_id, session=db)
    try:
        entry = await kb.add_text(
            content=body.content,
            title=body.title,
            category=body.category,
        )
    except Exception as e:
        logger.error("knowledge.add_text.error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Échec de l'ajout : {e}") from e
    return _to_response(entry)


@router.post("/pdf", response_model=KnowledgeEntryResponse, status_code=201)
async def add_pdf(
    request: Request,
    db: DbSession,
    file: Annotated[UploadFile, File(..., description="Fichier PDF à ingérer")],
    business_id: Annotated[UUID, Form(..., description="ID du business")],
    title: Annotated[str, Form(description="Titre du document")] = "",
    category: Annotated[str, Form(description="Catégorie")] = "general",
) -> KnowledgeEntryResponse:
    """upload un pdf."""
    _enforce_tenant(request, business_id)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Le fichier PDF est vide")

    kb = KnowledgeBase(business_id=business_id, session=db)
    try:
        entry = await kb.add_pdf(
            file_content=content,
            filename=file.filename,
            title=title,
            category=category,
        )
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Bibliothèque PDF manquante : {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _to_response(entry)


@router.get("/entries/{business_id}", response_model=list[KnowledgeEntryResponse])
async def list_entries(
    request: Request,
    db: DbSession,
    business_id: UUID,
) -> list[KnowledgeEntryResponse]:
    """liste les entrées."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    entries = await kb.list_entries()
    return [_to_response(e) for e in entries]


@router.delete("/entries/{business_id}/{entry_id}")
async def delete_entry(
    request: Request,
    db: DbSession,
    business_id: UUID,
    entry_id: str,
) -> dict:
    """supprime une entrée."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    if not await kb.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entrée non trouvée")
    return {"status": "deleted", "id": entry_id}


class UpdateEntryRequest(BaseModel):
    """maj d'une entrée texte."""

    title: str = Field("", description="Titre du document")
    content: str = Field(..., min_length=1, max_length=50000, description="Nouveau texte")
    category: str = Field("general", description="Catégorie")


@router.put("/entries/{business_id}/{entry_id}", response_model=KnowledgeEntryResponse)
async def update_entry(
    request: Request,
    db: DbSession,
    business_id: UUID,
    entry_id: str,
    body: UpdateEntryRequest,
) -> KnowledgeEntryResponse:
    """modifie une entrée."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    try:
        entry = await kb.update_text_entry(
            entry_id, content=body.content, title=body.title, category=body.category
        )
    except Exception as e:
        logger.error("knowledge.update_entry.error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Échec de la mise à jour : {e}") from e
    if entry is None:
        raise HTTPException(status_code=404, detail="Entrée non trouvée")
    return _to_response(entry)


class KnowledgeSearchHit(BaseModel):
    content: str
    score: float
    title: str | None = None
    category: str | None = None


@router.get("/search/{business_id}", response_model=list[KnowledgeSearchHit])
async def search_knowledge(
    request: Request,
    db: DbSession,
    business_id: UUID,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    top_k: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[KnowledgeSearchHit]:
    """recherche sémantique."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    try:
        docs = await kb.search(q, top_k=top_k)
    except Exception as e:
        logger.error("knowledge.search.error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Recherche impossible : {e}") from e
    return [
        KnowledgeSearchHit(
            content=d["content"],
            score=float(d.get("score") or 0.0),
            title=(d.get("metadata") or {}).get("title"),
            category=(d.get("metadata") or {}).get("category"),
        )
        for d in docs
    ]


class MultiImportResult(BaseModel):
    """résultat import multi-fichiers."""

    imported: list[KnowledgeEntryResponse]
    errors: list[dict]


@router.post("/files", response_model=MultiImportResult, status_code=201)
async def add_files(
    request: Request,
    db: DbSession,
    files: Annotated[list[UploadFile], File(..., description="PDF, .txt ou .md")],
    business_id: Annotated[UUID, Form(..., description="ID du business")],
    category: Annotated[str, Form(description="Catégorie")] = "general",
) -> MultiImportResult:
    """importe plusieurs fichiers."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    imported: list[KnowledgeEntryResponse] = []
    errors: list[dict] = []
    for file in files:
        name = file.filename or "sans-nom"
        try:
            content = await file.read()
            if not content:
                errors.append({"file": name, "error": "Fichier vide"})
                continue
            lower = name.lower()
            if lower.endswith(".pdf"):
                entry = await kb.add_pdf(
                    file_content=content, filename=name, title=name, category=category
                )
            elif lower.endswith((".txt", ".md")):
                text_content = content.decode("utf-8", errors="replace").strip()
                if not text_content:
                    errors.append({"file": name, "error": "Texte vide"})
                    continue
                entry = await kb.add_text(
                    content=text_content, title=name, category=category
                )
            else:
                errors.append({"file": name, "error": "Format non supporté (PDF, .txt, .md)"})
                continue
            imported.append(_to_response(entry))
        except Exception as e:
            # un échec n'arrête pas tout
            logger.error("knowledge.add_files.error", file=name, error=str(e))
            errors.append({"file": name, "error": str(e)})
    return MultiImportResult(imported=imported, errors=errors)


@router.get("/stats/{business_id}", response_model=KnowledgeStatsResponse)
async def get_stats(
    request: Request,
    db: DbSession,
    business_id: UUID,
) -> KnowledgeStatsResponse:
    """stats du business."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    stats = await kb.stats()
    return KnowledgeStatsResponse(**stats)

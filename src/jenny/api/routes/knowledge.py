"""Routes API pour la base de connaissances métier.

Permet au propriétaire du business de :
- Ajouter du texte (horaires, tarifs, FAQ, politique, etc.)
- Uploader un PDF (carte de prestations, règlement, etc.)
- Lister / supprimer les entrées de sa base de connaissances
- Voir les statistiques

Tout est persisté en base (document_embeddings) et vectorisé : Jenny s'y
réfère via le RAG pour répondre aux clients.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003 — utilisé dans les annotations de route (FastAPI runtime)

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from jenny.api.dependencies import DbSession  # noqa: TC001 — résolu au runtime par FastAPI
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.rag.knowledge_base import KnowledgeBase, KnowledgeEntry

logger = get_logger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


# ── Schémas ──


class AddTextRequest(BaseModel):
    """Requête pour ajouter du texte à la base de connaissances."""

    business_id: UUID = Field(..., description="ID du business")
    title: str = Field("", description="Titre du document")
    content: str = Field(..., min_length=1, max_length=50000, description="Texte à mémoriser")
    category: str = Field(
        "general",
        description="Catégorie : horaires, tarifs, faq, politique, services, equipe, general",
    )


class KnowledgeEntryResponse(BaseModel):
    """Réponse avec les détails d'une entrée."""

    id: str
    business_id: str
    title: str
    content_preview: str
    source: str
    category: str
    chunks_count: int
    created_at: str


class KnowledgeStatsResponse(BaseModel):
    """Statistiques de la base de connaissances."""

    business_id: str
    total_entries: int
    total_chunks: int
    by_category: dict[str, int]
    by_source: dict[str, int]


# ── Helpers ──


def _enforce_tenant(request: Request, business_id: UUID) -> None:
    """Si l'auth est requise, le business ciblé doit correspondre au contexte JWT."""
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


# ── Routes ──


@router.post("/text", response_model=KnowledgeEntryResponse, status_code=201)
async def add_text(
    request: Request,
    body: AddTextRequest,
    db: DbSession,
) -> KnowledgeEntryResponse:
    """Ajoute du texte libre à la base de connaissances (horaires, tarifs, FAQ...)."""
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
    """Upload un PDF (carte des prestations, règlement, catalogue...) dans la base."""
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
    """Liste toutes les entrées de la base de connaissances d'un business."""
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
    """Supprime une entrée de la base de connaissances."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    if not await kb.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entrée non trouvée")
    return {"status": "deleted", "id": entry_id}


class UpdateEntryRequest(BaseModel):
    """Mise à jour d'une entrée texte (remplace son contenu)."""

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
    """Modifie une entrée existante de la base de connaissances (#12).

    Re-découpe et re-vectorise le nouveau contenu sous le même identifiant.
    """
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
    """Recherche sémantique dans la base de connaissances du business (#12)."""
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
    """Résultat d'un import multi-fichiers (#13)."""

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
    """Importe plusieurs fichiers d'un coup (PDF/texte) dans la base (#13).

    Chaque fichier est traité indépendamment : un échec n'interrompt pas les
    autres ; les erreurs sont renvoyées fichier par fichier.
    """
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
            # On isole l'échec par fichier : un fichier KO n'arrête pas les autres.
            logger.error("knowledge.add_files.error", file=name, error=str(e))
            errors.append({"file": name, "error": str(e)})
    return MultiImportResult(imported=imported, errors=errors)


@router.get("/stats/{business_id}", response_model=KnowledgeStatsResponse)
async def get_stats(
    request: Request,
    db: DbSession,
    business_id: UUID,
) -> KnowledgeStatsResponse:
    """Statistiques de la base de connaissances d'un business."""
    _enforce_tenant(request, business_id)
    kb = KnowledgeBase(business_id=business_id, session=db)
    stats = await kb.stats()
    return KnowledgeStatsResponse(**stats)

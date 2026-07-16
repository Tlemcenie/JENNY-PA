"""pipeline d'ingestion rag."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.rag.embeddings import BaseEmbedder
    from jenny.rag.vector_store import PgVectorStore

logger = get_logger(__name__)


@dataclass
class DocumentChunk:
    """chunk prêt à indexer."""

    id: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid4())


class DocumentIngester:
    """ingère les documents en base."""

    def __init__(
        self,
        embedder: BaseEmbedder | None = None,
        vector_store: PgVectorStore | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        collection: str = "default",
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.collection = collection

    def chunk_text(
        self,
        text: str,
        metadata: dict | None = None,
    ) -> list[DocumentChunk]:
        """découpe en chunks."""
        # découpe en phrases
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())

        chunks: list[DocumentChunk] = []
        current_chunk: list[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence)

            if current_length + sentence_length > self.chunk_size and current_chunk:
                # sauvegarde le chunk
                chunk_text = " ".join(current_chunk)
                chunks.append(
                    DocumentChunk(
                        content=chunk_text,
                        metadata={**(metadata or {}), "chunk_index": len(chunks)},
                    )
                )

                # overlap sur la fin
                overlap_text = ""
                overlap_sentences: list[str] = []
                for s in reversed(current_chunk):
                    if len(overlap_text) + len(s) <= self.chunk_overlap:
                        overlap_sentences.insert(0, s)
                        overlap_text = " ".join(overlap_sentences)
                    else:
                        break

                current_chunk = overlap_sentences
                current_length = len(overlap_text)

            current_chunk.append(sentence)
            current_length += sentence_length

        # dernier chunk
        if current_chunk:
            chunks.append(
                DocumentChunk(
                    content=" ".join(current_chunk),
                    metadata={**(metadata or {}), "chunk_index": len(chunks)},
                )
            )

        logger.info("ingestion.chunked", num_chunks=len(chunks))
        return chunks

    async def ingest_text(
        self,
        content: str,
        metadata: dict | None = None,
    ) -> int:
        """ingère un texte."""
        # découpage
        chunks = self.chunk_text(content, metadata)

        # embeddings
        if self.embedder is not None:
            texts = [c.content for c in chunks]
            embeddings = await self.embedder.embed_batch(texts)
            for chunk, embedding in zip(chunks, embeddings, strict=False):
                chunk.embedding = embedding
        else:
            logger.warning("ingestion.no_embedder")

        # stockage pgvector
        if self.vector_store is not None and chunks[0].embedding is not None:
            documents = [
                {
                    "content": c.content,
                    "embedding": c.embedding,
                    "metadata": c.metadata,
                }
                for c in chunks
                if c.embedding is not None
            ]
            await self.vector_store.add_documents(documents)
        else:
            logger.warning("ingestion.no_vector_store")

        logger.info("ingestion.done", num_chunks=len(chunks))
        return len(chunks)

    async def ingest_file(
        self,
        file_path: str | Path,
        metadata: dict | None = None,
    ) -> int:
        """ingère un fichier."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier non trouvé : {path}")

        content = path.read_text(encoding="utf-8")
        file_metadata = {
            "source": str(path),
            "filename": path.name,
            **(metadata or {}),
        }

        logger.info("ingestion.file", path=str(path), size=len(content))
        return await self.ingest_text(content, file_metadata)

    async def ingest_directory(
        self,
        directory: str | Path,
        extensions: list[str] | None = None,
        metadata: dict | None = None,
    ) -> int:
        """ingère tout un dossier."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Répertoire non trouvé : {dir_path}")

        exts = extensions or [".txt", ".md"]
        total_chunks = 0

        for file_path in sorted(dir_path.rglob("*")):
            if file_path.suffix in exts and file_path.is_file():
                chunks = await self.ingest_file(file_path, metadata)
                total_chunks += chunks

        logger.info(
            "ingestion.directory_done",
            directory=str(dir_path),
            total_chunks=total_chunks,
        )
        return total_chunks

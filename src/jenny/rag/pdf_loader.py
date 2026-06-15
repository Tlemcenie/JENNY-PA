"""Chargeur de fichiers PDF pour la base de connaissances RAG.

Extrait le texte des fichiers PDF pour l'ingérer dans le vector store.
Jenny peut ensuite s'y référer pour répondre aux questions métier.

Backends supportés :
1. PyMuPDF (fitz) — rapide, précis
2. pdfplumber — bonne extraction de tableaux
3. Fallback texte brut si aucune lib n'est installée
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PDFPage:
    """Page extraite d'un PDF."""

    page_number: int
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class PDFDocument:
    """Document PDF entièrement extrait."""

    filename: str
    pages: list[PDFPage]
    total_pages: int
    metadata: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """Texte complet du document (toutes les pages concaténées)."""
        return "\n\n".join(p.text for p in self.pages if p.text.strip())


class PDFLoader:
    """Charge et extrait le texte des fichiers PDF.

    Essaie d'utiliser PyMuPDF (fitz) d'abord, puis pdfplumber,
    puis un fallback basique.

    Usage :
        loader = PDFLoader()
        doc = loader.load_file("mon_document.pdf")
        print(doc.full_text)
    """

    def load_file(self, file_path: str | Path) -> PDFDocument:
        """Charge un PDF depuis un fichier.

        Args:
            file_path: Chemin vers le fichier PDF.

        Returns:
            PDFDocument avec le texte extrait de chaque page.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier PDF non trouvé : {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Le fichier n'est pas un PDF : {path.suffix}")

        content = path.read_bytes()
        return self.load_bytes(content, filename=path.name)

    def load_bytes(self, content: bytes, filename: str = "document.pdf") -> PDFDocument:
        """Charge un PDF depuis des bytes (upload).

        Args:
            content: Contenu binaire du PDF.
            filename: Nom du fichier.

        Returns:
            PDFDocument avec le texte extrait.
        """
        # Essayer PyMuPDF
        try:
            return self._extract_with_pymupdf(content, filename)
        except ImportError:
            logger.debug("pdf.pymupdf_not_available")

        # Essayer pdfplumber
        try:
            return self._extract_with_pdfplumber(content, filename)
        except ImportError:
            logger.debug("pdf.pdfplumber_not_available")

        raise ImportError(
            "Aucune bibliothèque PDF installée. "
            "Installez PyMuPDF (pip install PyMuPDF) "
            "ou pdfplumber (pip install pdfplumber)."
        )

    def _extract_with_pymupdf(self, content: bytes, filename: str) -> PDFDocument:
        """Extraction via PyMuPDF (fitz) — recommandé."""
        import fitz  # PyMuPDF

        pages: list[PDFPage] = []

        with fitz.open(stream=content, filetype="pdf") as doc:
            for i, page in enumerate(doc):
                text = page.get_text("text")
                pages.append(
                    PDFPage(
                        page_number=i + 1,
                        text=text,
                        metadata={"width": page.rect.width, "height": page.rect.height},
                    )
                )

            metadata = {k: v for k, v in doc.metadata.items() if v}

        logger.info(
            "pdf.extracted.pymupdf",
            filename=filename,
            pages=len(pages),
        )

        return PDFDocument(
            filename=filename,
            pages=pages,
            total_pages=len(pages),
            metadata=metadata,
        )

    def _extract_with_pdfplumber(self, content: bytes, filename: str) -> PDFDocument:
        """Extraction via pdfplumber — bon pour les tableaux."""
        import pdfplumber

        pages: list[PDFPage] = []

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                pages.append(
                    PDFPage(
                        page_number=i + 1,
                        text=text,
                        metadata={"width": page.width, "height": page.height},
                    )
                )

        logger.info(
            "pdf.extracted.pdfplumber",
            filename=filename,
            pages=len(pages),
        )

        return PDFDocument(
            filename=filename,
            pages=pages,
            total_pages=len(pages),
            metadata={"extractor": "pdfplumber"},
        )

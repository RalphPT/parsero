"""Document loader for fetching and processing documents from URLs."""
import hashlib
from io import BytesIO
import httpx
from pypdf import PdfReader

from app.core.exceptions import DocumentLoadError


class DocumentLoader:
    """Load and process documents from URLs."""

    MAX_SIZE = 5 * 1024 * 1024  # 5 MB
    MAX_CHARS = 50_000

    @staticmethod
    async def load_and_hash(url: str) -> tuple[str, str]:
        """
        Descarga documento, calcula SHA-256 y extrae texto.

        Returns:
            (document_text, sha256_hash)

        Raises:
            DocumentLoadError: si la descarga, tamaño o formato no son válidos.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
            except Exception as e:
                raise DocumentLoadError(f"No se pudo descargar el documento: {e}") from e

        content = response.content
        if len(content) > DocumentLoader.MAX_SIZE:
            raise DocumentLoadError(
                f"Documento demasiado grande: {len(content)} bytes (max {DocumentLoader.MAX_SIZE})"
            )

        content_hash = hashlib.sha256(content).hexdigest()

        content_type = response.headers.get("content-type", "").lower()
        url_lower = url.lower()
        # Detectar PDF por header, extension o magic number (Google Drive y otros
        # CDN devuelven octet-stream sin pdf en content-type ni en URL).
        is_pdf = (
            "pdf" in content_type
            or url_lower.endswith(".pdf")
            or content[:4] == b"%PDF"
        )
        if is_pdf:
            text = DocumentLoader._extract_pdf_text(content)
        elif "text" in content_type or url_lower.endswith((".txt", ".md")):
            text = content.decode("utf-8", errors="ignore")
        else:
            raise DocumentLoadError(
                f"Content-Type no soportado: {content_type} (solo PDF y texto)"
            )

        if len(text) > DocumentLoader.MAX_CHARS:
            text = text[: DocumentLoader.MAX_CHARS]

        return text, content_hash

    @staticmethod
    def _extract_pdf_text(content: bytes) -> str:
        try:
            pdf_reader = PdfReader(BytesIO(content))
            text_parts = []
            for page in pdf_reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text_parts.append(extracted)
            text = "\n".join(text_parts)
            if not text.strip():
                raise DocumentLoadError("PDF sin texto extraíble (¿escaneado?)")
            return text
        except DocumentLoadError:
            raise
        except Exception as e:
            raise DocumentLoadError(f"Error parseando PDF: {e}") from e

"""
SignalForge Product Knowledge Vector Store -- Phase 5.

Provides a persistent, local ChromaDB-backed vector store for product
knowledge retrieval. Product documents are loaded with LangChain document
loaders, split into chunks, embedded, and stored with source metadata so
later phases can retrieve grounded context for response drafting.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import chromadb
from chromadb.config import Settings as ChromaSettings

try:
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
except Exception:  # pragma: no cover - dependency mismatch fallback
    try:
        from langchain.document_loaders import DirectoryLoader, TextLoader
    except Exception:  # pragma: no cover - local compatibility shim
        from langchain_core.documents import Document

        class TextLoader:  # type: ignore[no-redef]
            """Small compatibility shim when LangChain loader packages are broken."""

            def __init__(
                self,
                file_path: str,
                encoding: str = "utf-8",
                autodetect_encoding: bool = False,
            ) -> None:
                self._file_path = Path(file_path)
                self._encoding = encoding
                self._autodetect_encoding = autodetect_encoding

            def load(self):
                encodings = [self._encoding]
                if self._autodetect_encoding:
                    encodings.extend(["utf-8-sig", "cp1252", "latin-1"])

                last_error = None
                for encoding in dict.fromkeys(encodings):
                    try:
                        content = self._file_path.read_text(encoding=encoding)
                        return [
                            Document(
                                page_content=content,
                                metadata={"source": str(self._file_path)},
                            )
                        ]
                    except UnicodeDecodeError as exc:
                        last_error = exc

                if last_error is not None:
                    raise last_error
                raise ValueError(f"Unable to load file: {self._file_path}")

        class DirectoryLoader:  # type: ignore[no-redef]
            """Small compatibility shim mirroring the loader API we need."""

            def __init__(
                self,
                path: str,
                glob: str = "**/*",
                loader_cls=TextLoader,
                loader_kwargs: Optional[Dict[str, Any]] = None,
            ) -> None:
                self._path = Path(path)
                self._glob = glob
                self._loader_cls = loader_cls
                self._loader_kwargs = loader_kwargs or {}

            def load(self):
                documents = []
                for file_path in sorted(self._path.glob(self._glob)):
                    if not file_path.is_file():
                        continue
                    loader = self._loader_cls(
                        str(file_path),
                        **self._loader_kwargs,
                    )
                    documents.extend(loader.load())
                return documents

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - compatibility fallback
    from langchain.text_splitter import RecursiveCharacterTextSplitter

logger = logging.getLogger("signalforge.vector_store")

_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class VectorStoreConfig:
    """Configuration for the local ChromaDB product knowledge store."""

    documents_path: Path
    persist_directory: Path
    collection_name: str = "signalforge_product_knowledge"
    chunk_size: int = 700
    chunk_overlap: int = 120
    gemini_embedding_model: str = "models/text-embedding-004"
    fallback_dimensions: int = 256


class HashEmbeddingProvider:
    """
    Deterministic local embedding fallback.

    This avoids external API calls during local development and tests while
    still providing stable semantic-enough retrieval for small document sets.
    """

    name = "localhash"

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be > 0")
        self._dimensions = dimensions

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed_text(text)

    def _embed_text(self, text: str) -> List[float]:
        tokens = _TOKEN_PATTERN.findall(text.lower())
        vector = [0.0] * self._dimensions

        if not tokens:
            return vector

        counts = Counter(tokens)
        for token, weight in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = -1.0 if digest[4] % 2 else 1.0
            vector[index] += float(weight) * sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector

        return [value / norm for value in vector]

    def __repr__(self) -> str:
        return f"<HashEmbeddingProvider dimensions={self._dimensions}>"


class GeminiEmbeddingProvider:
    """Gemini embedding wrapper used when credentials and SDK are available."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model_name: str = "models/text-embedding-004",
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for Gemini embeddings")

        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=model_name,
            google_api_key=api_key,
        )
        self._model_name = model_name

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return self._embeddings.embed_documents(list(texts))

    def embed_query(self, text: str) -> List[float]:
        return self._embeddings.embed_query(text)

    def __repr__(self) -> str:
        return f"<GeminiEmbeddingProvider model='{self._model_name}'>"


class LocalChromaVectorStore:
    """
    Persistent ChromaDB store for SignalForge product knowledge.

    Responsibilities:
      - ingest markdown product docs via LangChain loaders
      - chunk documents for retrieval
      - store embeddings and metadata in a local persistent DB
      - retrieve the most relevant chunks for an opportunity query
    """

    def __init__(
        self,
        documents_path: Optional[str] = None,
        persist_directory: Optional[str] = None,
        collection_name: str = "signalforge_product_knowledge",
        chunk_size: int = 700,
        chunk_overlap: int = 120,
        gemini_api_key: Optional[str] = None,
        gemini_embedding_model: str = "models/text-embedding-004",
        fallback_dimensions: int = 256,
    ) -> None:
        project_root = Path(__file__).resolve().parent.parent
        documents_root = Path(documents_path) if documents_path else (
            project_root / "knowledge" / "product_docs"
        )
        persist_root = Path(persist_directory) if persist_directory else (
            project_root / "knowledge" / "vector_db"
        )

        self.config = VectorStoreConfig(
            documents_path=documents_root,
            persist_directory=persist_root,
            collection_name=collection_name,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            gemini_embedding_model=gemini_embedding_model,
            fallback_dimensions=fallback_dimensions,
        )
        self._project_root = project_root
        self.config.persist_directory.mkdir(parents=True, exist_ok=True)

        self._embedding_provider = self._build_embedding_provider(gemini_api_key)
        self._collection_name = (
            f"{self.config.collection_name}_{self._embedding_provider.name}"
        )
        chroma_settings = ChromaSettings(
            anonymized_telemetry=False,
            allow_reset=True,
            is_persistent=True,
            persist_directory=str(self.config.persist_directory),
        )
        self._client = chromadb.PersistentClient(
            path=str(self.config.persist_directory),
            settings=chroma_settings,
        )
        self._collection = self._get_or_create_collection()
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        logger.info(
            "LocalChromaVectorStore initialised - collection=%s, provider=%s, persist=%s",
            self._collection_name,
            self.embedding_provider_name,
            self.config.persist_directory,
        )

    def ingest_documents(self) -> Dict[str, Any]:
        """
        Load markdown docs, chunk them, embed them, and persist them locally.
        """
        documents_path = self.config.documents_path
        if not documents_path.exists():
            raise FileNotFoundError(
                f"Knowledge documents path does not exist: {documents_path}"
            )

        documents = self._load_documents(documents_path)
        if not documents:
            raise ValueError(f"No markdown documents found under {documents_path}")

        chunks = self._text_splitter.split_documents(documents)
        if not chunks:
            raise ValueError("Document ingestion produced zero chunks")

        total_chunks_by_source = Counter(
            str(chunk.metadata.get("source", "unknown")) for chunk in chunks
        )
        chunk_indices = Counter()

        ids: List[str] = []
        texts: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for chunk in chunks:
            content = self._normalise_whitespace(chunk.page_content)
            if not content:
                continue

            source = str(chunk.metadata.get("source", "unknown"))
            chunk_index = chunk_indices[source]
            chunk_indices[source] += 1
            chunk_id = self._build_chunk_id(source, chunk_index, content)

            metadata = dict(chunk.metadata)
            metadata.update({
                "chunk_index": int(chunk_index),
                "document_total_chunks": int(total_chunks_by_source[source]),
                "chunk_size": int(len(content)),
                "chunk_id": chunk_id,
            })

            ids.append(chunk_id)
            texts.append(content)
            metadatas.append(self._serialise_metadata(metadata))

        if not texts:
            raise ValueError("All generated chunks were empty after normalisation")

        embeddings = self._embedding_provider.embed_documents(texts)

        self.reset_collection()
        self._collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        stats = {
            "documents_loaded": len(documents),
            "chunks_stored": len(texts),
            "collection_name": self.collection_name,
            "embedding_provider": self.embedding_provider_name,
            "persist_directory": str(self.config.persist_directory),
        }
        logger.info(
            "Ingested %d documents into %d chunks (%s)",
            stats["documents_loaded"],
            stats["chunks_stored"],
            self.collection_name,
        )
        return stats

    def retrieve_context(self, query: str, top_k: int = 3) -> List[Dict[str, str]]:
        """
        Retrieve the most relevant product knowledge chunks for a query.

        Returns:
            [
                {"content": "...", "source": "..."},
                ...
            ]
        """
        query_text = self._normalise_whitespace(query)
        if not query_text:
            return []
        if top_k <= 0:
            return []

        self.ensure_ingested()
        if self.document_count == 0:
            return []

        query_embedding = self._embedding_provider.embed_query(query_text)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.document_count),
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])
        metadatas = results.get("metadatas", [[]])
        retrieved_docs = documents[0] if documents else []
        retrieved_meta = metadatas[0] if metadatas else []

        payload: List[Dict[str, str]] = []
        for content, metadata in zip(retrieved_docs, retrieved_meta):
            if not content:
                continue
            source = "unknown"
            if isinstance(metadata, dict):
                source = str(metadata.get("source", source))
            payload.append({
                "content": self._normalise_whitespace(str(content)),
                "source": source,
            })

        logger.info(
            "Retrieved %d context chunks for query '%s'",
            len(payload),
            query_text[:80],
        )
        return payload

    def ensure_ingested(self) -> None:
        """Build the index on first use if the persistent collection is empty."""
        if self.document_count == 0:
            self.ingest_documents()

    def reset_collection(self) -> None:
        """Delete and recreate the underlying collection."""
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:
            pass
        self._collection = self._get_or_create_collection()

    @property
    def collection(self):
        return self._collection

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def document_count(self) -> int:
        return int(self._collection.count())

    @property
    def embedding_provider_name(self) -> str:
        return self._embedding_provider.name

    def _build_embedding_provider(
        self,
        gemini_api_key: Optional[str],
    ):
        api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        if api_key:
            try:
                provider = GeminiEmbeddingProvider(
                    api_key=api_key,
                    model_name=self.config.gemini_embedding_model,
                )
                logger.info(
                    "Using Gemini embeddings for vector store (%s)",
                    self.config.gemini_embedding_model,
                )
                return provider
            except Exception as exc:
                logger.warning(
                    "Gemini embeddings unavailable, falling back to local hash embeddings: %s",
                    exc,
                )

        logger.info("Using deterministic local hash embeddings for vector store")
        return HashEmbeddingProvider(dimensions=self.config.fallback_dimensions)

    def _get_or_create_collection(self):
        metadata = {
            "embedding_provider": self.embedding_provider_name,
            "chunk_size": int(self.config.chunk_size),
            "chunk_overlap": int(self.config.chunk_overlap),
        }
        return self._client.get_or_create_collection(
            name=self._collection_name,
            metadata=metadata,
        )

    def _load_documents(self, documents_path: Path):
        loader_kwargs = {"encoding": "utf-8", "autodetect_encoding": True}
        try:
            loader = DirectoryLoader(
                str(documents_path),
                glob="**/*.md",
                loader_cls=TextLoader,
                loader_kwargs=loader_kwargs,
            )
        except TypeError:  # pragma: no cover - older TextLoader signature
            loader = DirectoryLoader(
                str(documents_path),
                glob="**/*.md",
                loader_cls=TextLoader,
                loader_kwargs={"encoding": "utf-8"},
            )

        documents = loader.load()
        documents.sort(key=lambda item: str(item.metadata.get("source", "")))

        for document in documents:
            source = self._normalise_source_path(
                str(document.metadata.get("source", "unknown"))
            )
            document.metadata["source"] = source
            document.metadata["document_name"] = Path(source).name
            document.metadata["document_stem"] = Path(source).stem

        return documents

    def _normalise_source_path(self, source_path: str) -> str:
        raw_path = Path(source_path)
        try:
            resolved = raw_path.resolve()
            relative = resolved.relative_to(self._project_root.resolve())
            return relative.as_posix()
        except Exception:
            return raw_path.name or source_path

    @staticmethod
    def _normalise_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _serialise_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        serialised: Dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                serialised[key] = value
            elif value is None:
                serialised[key] = ""
            else:
                serialised[key] = str(value)
        return serialised

    @staticmethod
    def _build_chunk_id(source: str, chunk_index: int, content: str) -> str:
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
        return f"{source}::chunk::{chunk_index}::{digest}"

    def __repr__(self) -> str:
        return (
            f"<LocalChromaVectorStore collection='{self.collection_name}' "
            f"provider='{self.embedding_provider_name}' chunks={self.document_count}>"
        )


ProductKnowledgeVectorStore = LocalChromaVectorStore

__all__ = [
    "VectorStoreConfig",
    "HashEmbeddingProvider",
    "GeminiEmbeddingProvider",
    "LocalChromaVectorStore",
    "ProductKnowledgeVectorStore",
]

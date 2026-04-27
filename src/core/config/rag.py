"""Настройки RAG (Retrieval-Augmented Generation)."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("RAGSettings", "rag_settings")


class RAGSettings(BaseSettingsWithLoader):
    """Конфигурация RAG pipeline."""

    yaml_group: ClassVar[str] = "rag"
    model_config = SettingsConfigDict(env_prefix="RAG_", extra="forbid")

    vector_backend: str = Field(
        "chroma", description="Vector store backend: chroma, faiss."
    )
    embedding_model: str = Field(
        "all-MiniLM-L6-v2", description="Модель для эмбеддингов."
    )
    chunk_size: int = Field(512, ge=64, description="Размер чанка (символов).")
    chunk_overlap: int = Field(50, ge=0, description="Перекрытие чанков.")
    chroma_host: str = Field("localhost", description="Хост Chroma DB.")
    chroma_port: int = Field(8000, gt=0, lt=65536, description="Порт Chroma DB.")
    chroma_collection: str = Field("gd_rag", description="Коллекция по умолчанию.")
    top_k: int = Field(5, ge=1, le=100, description="Кол-во результатов поиска.")
    enabled: bool = Field(False, description="Включить RAG.")


rag_settings = RAGSettings()

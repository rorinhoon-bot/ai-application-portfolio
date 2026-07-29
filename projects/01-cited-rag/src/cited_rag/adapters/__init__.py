"""External format and service adapters."""

from cited_rag.adapters.mimo import MiMoClient
from cited_rag.config import Settings
from cited_rag.model_client import AnswerModelClient


def create_answer_model_client(settings: Settings) -> AnswerModelClient:
    """Create only explicitly supported model providers."""

    if settings.model_provider == "mimo":
        return MiMoClient(settings)
    raise ValueError(f"unsupported model provider: {settings.model_provider}")


__all__ = ["MiMoClient", "create_answer_model_client"]

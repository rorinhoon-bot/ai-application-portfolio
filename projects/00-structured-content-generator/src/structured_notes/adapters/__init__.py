from collections.abc import Callable, Mapping

from structured_notes.config import Settings
from structured_notes.adapters.mimo import MiMoClient
from structured_notes.errors import AppError, ErrorCode, ExitCode
from structured_notes.model_client import ModelClient

ProviderFactory = Callable[[Settings], ModelClient]
PROVIDER_FACTORIES: Mapping[str, ProviderFactory] = {
    "mimo": MiMoClient,
}


def create_model_client(
    settings: Settings,
    *,
    provider_factories: Mapping[str, ProviderFactory] = PROVIDER_FACTORIES,
) -> ModelClient:
    factory = provider_factories.get(settings.model_provider)
    if factory is None:
        raise AppError(
            ErrorCode.UNKNOWN_MODEL_PROVIDER,
            "未注册的模型供应商。",
            retryable=False,
            exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
        )
    return factory(settings)

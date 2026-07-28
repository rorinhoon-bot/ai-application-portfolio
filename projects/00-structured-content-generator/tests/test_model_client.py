from structured_notes.model_client import ModelClient
from structured_notes.models import ModelRequest, ModelResponse


class FakeModelClient:
    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content='{"title":"test"}')


def test_model_request_keeps_prompt_payload_and_schema_separate() -> None:
    request = ModelRequest(
        system_prompt="Follow the schema.",
        user_payload={"topic": "Transformer", "material": "untrusted text"},
        response_schema={"type": "object"},
    )

    assert request.system_prompt == "Follow the schema."
    assert request.user_payload["material"] == "untrusted text"
    assert request.response_schema == {"type": "object"}


def test_model_response_allows_empty_content_for_service_validation() -> None:
    response = ModelResponse(content="")

    assert response.content == ""


def test_fake_client_satisfies_model_client_protocol_by_structure() -> None:
    client: ModelClient = FakeModelClient()
    request = ModelRequest(
        system_prompt="Follow the schema.",
        user_payload={},
        response_schema={},
    )

    assert client.generate(request).content == '{"title":"test"}'

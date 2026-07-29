"""Stable domain errors."""


class CitedRagError(ValueError):
    """Base class with a stable public error code."""

    code = "INTERNAL_ERROR"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{self.code}: {reason}")


class DocumentParseError(CitedRagError):
    """Raised when HTML cannot produce trustworthy document evidence."""

    code = "DOCUMENT_PARSE_ERROR"


class ChunkingError(CitedRagError):
    """Raised when blocks cannot produce trustworthy chunk evidence."""

    code = "CHUNKING_ERROR"


class EmbeddingError(CitedRagError):
    """Raised when an embedding provider cannot preserve the input contract."""

    code = "EMBEDDING_ERROR"


class EmbeddingInputTooLongError(CitedRagError):
    """Raised before inference when an input exceeds the pinned token limit."""

    code = "EMBEDDING_INPUT_TOO_LONG"


class VectorDimensionMismatchError(CitedRagError):
    """Raised when a provider returns an unexpected vector dimension."""

    code = "VECTOR_DIMENSION_MISMATCH"


class VectorValueInvalidError(CitedRagError):
    """Raised when a vector contains invalid values or has zero norm."""

    code = "VECTOR_VALUE_INVALID"


class IndexBuildError(CitedRagError):
    """Raised when a non-active index build cannot be completed."""

    code = "INDEX_BUILD_ERROR"


class IndexVersionMismatchError(CitedRagError):
    """Raised when an active index has a different logical specification."""

    code = "INDEX_VERSION_MISMATCH"


class IndexConsistencyError(CitedRagError):
    """Raised when index metadata and physical state disagree."""

    code = "INDEX_CONSISTENCY_ERROR"


class RetrievalInputError(CitedRagError):
    """Raised when a retrieval request violates the public input contract."""

    code = "RETRIEVAL_INPUT_ERROR"


class RetrievalError(CitedRagError):
    """Raised when a validated query cannot be retrieved."""

    code = "RETRIEVAL_ERROR"


class ModelTimeoutError(CitedRagError):
    """Raised when the model request exceeds its configured timeout."""

    code = "MODEL_TIMEOUT"


class ModelNetworkError(CitedRagError):
    """Raised when no model HTTP response is received."""

    code = "MODEL_NETWORK_ERROR"


class ModelHttpError(CitedRagError):
    """Raised when the model provider returns a non-success status."""

    code = "MODEL_HTTP_ERROR"

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"model API returned HTTP {status_code}")


class InvalidModelJsonError(CitedRagError):
    """Raised when model text is not one valid JSON object."""

    code = "INVALID_MODEL_JSON"


class ModelOutputError(CitedRagError):
    """Raised when model JSON violates the answer contract."""

    code = "MODEL_OUTPUT_ERROR"


class InvalidCitationIdError(CitedRagError):
    """Raised when a model cites evidence outside this retrieval result."""

    code = "INVALID_CITATION_ID"


class EvaluationError(CitedRagError):
    """Raised when a fixed evaluation contract cannot be executed."""

    code = "EVALUATION_ERROR"


class PathOutsideAllowedRootError(CitedRagError):
    """Raised when a resolved source path escapes its configured root."""

    code = "PATH_OUTSIDE_ALLOWED_ROOT"


class SourceHashMismatchError(CitedRagError):
    """Raised when file bytes do not match the approved manifest hash."""

    code = "SOURCE_HASH_MISMATCH"


class SourceManifestError(CitedRagError):
    """Raised when source metadata and parsed HTML disagree."""

    code = "SOURCE_MANIFEST_ERROR"


class CorpusSnapshotError(CitedRagError):
    """Raised when a packaged corpus cannot be trusted or restored."""

    code = "CORPUS_SNAPSHOT_ERROR"


class UnsupportedDocumentTypeError(CitedRagError):
    """Raised when a source is not an allowed HTML file."""

    code = "UNSUPPORTED_DOCUMENT_TYPE"

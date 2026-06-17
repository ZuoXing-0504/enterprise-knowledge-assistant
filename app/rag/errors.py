class DocumentProcessingError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class EmbeddingServiceError(DocumentProcessingError):
    pass


class ChatServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable

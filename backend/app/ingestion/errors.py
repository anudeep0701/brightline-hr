from app.schemas.ingestion import IngestResult


class IngestionBatchError(Exception):
    """Safe batch failure with counts. Never includes submitted values or credentials."""

    def __init__(self, status_code: int, code: str, detail: str, result: IngestResult):
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.result = result
        super().__init__(detail)

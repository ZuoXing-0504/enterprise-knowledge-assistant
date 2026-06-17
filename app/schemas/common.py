from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None


class ApiResponse[DataT](BaseModel):
    success: bool = True
    data: DataT | None = None
    error: ErrorDetail | None = None
    request_id: str | None = None


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class PageResponse[ItemT](BaseModel):
    items: list[ItemT]
    pagination: PaginationMeta

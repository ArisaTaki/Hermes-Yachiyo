"""错误 Schema 定义"""

from pydantic import BaseModel

from .enums import ErrorCode


class ErrorResponse(BaseModel):
    """统一错误响应"""

    error: ErrorCode
    message: str
    detail: str | None = None

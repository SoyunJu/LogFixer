from fastapi import Request
from fastapi.responses import JSONResponse


class LogFixerException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class IncidentNotFoundException(LogFixerException):
    def __init__(self, log_hash: str):
        super().__init__(status_code=404, detail=f"Incident not found: {log_hash}")


class InvalidStateTransitionException(LogFixerException):
    def __init__(self, current: str, target: str):
        super().__init__(
            status_code=409,
            detail=f"상태 전이 불가: {current} → {target}",
        )


# FastAPI 앱에 등록할 전역 예외 핸들러
async def logfixer_exception_handler(request: Request, exc: LogFixerException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
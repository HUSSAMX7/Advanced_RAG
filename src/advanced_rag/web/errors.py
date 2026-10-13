"""HTTP error adapters shared by the feature routers."""

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .files.processing import LibraryConflict
from .files.services import UploadTooLarge


async def invalid_input(request, exc):
    return JSONResponse(
        {"detail": "قيمة غير صالحة في الطلب. راجع الحقول وحاول مجددًا."}, status_code=422
    )


async def not_found(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=404)


async def conflict(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


async def bad_value(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


async def upload_too_large(request, exc):
    return JSONResponse({"detail": "حجم الملف أكبر من الحد المسموح."}, status_code=413)


def register(app):
    for error, handler in (
        (RequestValidationError, invalid_input),
        (FileNotFoundError, not_found),
        (LibraryConflict, conflict),
        (ValueError, bad_value),
        (UploadTooLarge, upload_too_large),
    ):
        app.add_exception_handler(error, handler)

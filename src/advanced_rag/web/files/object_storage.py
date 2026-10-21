"""Private document bytes in Supabase; local files are a processing cache.

All calls run in worker threads. The server key never reaches response bodies.
"""

import asyncio
import mimetypes
import tempfile
from pathlib import Path
from urllib.parse import quote

import httpx


class StorageUnavailable(Exception):
    """Distinguishes remote storage failures for the HTTP 503 adapter."""


async def run(operation, *args):
    """Drain in-flight storage work before an owner's workspace can be purged."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


def enabled(settings):
    if bool(settings.rag_supabase_url) != bool(settings.rag_supabase_secret_key):
        raise ValueError("اضبط رابط Supabase ومفتاحه السري معًا لتخزين الملفات.")
    return bool(settings.rag_supabase_url)


def client(settings):
    return httpx.Client(
        base_url=settings.rag_supabase_url.rstrip("/") + "/storage/v1/",
        headers={"apikey": settings.rag_supabase_secret_key.get_secret_value()},
        timeout=settings.rag_supabase_timeout_seconds,
        follow_redirects=False,
    )


def request(connection, method, path, **kwargs):
    try:
        response = connection.request(method, path, **kwargs)
        if not response.is_success:
            raise StorageUnavailable("تعذر الوصول إلى تخزين الملفات. حاول مرة أخرى.")
        return response
    except httpx.HTTPError:
        raise StorageUnavailable("تعذر الاتصال بتخزين الملفات. حاول مرة أخرى.") from None


def bucket(settings):
    return quote(settings.rag_supabase_bucket, safe="")


def object_key(settings, original):
    # Namespaces are assigned by identity/assistant services, never by the caller.
    parts = settings.document_storage_prefix.split("/") + ["uploads", original]
    if any(not part or part in {".", ".."} or "\\" in part for part in parts):
        raise ValueError("مسار تخزين غير صالح.")
    if "/" in original:
        raise ValueError("اسم تخزين غير صالح.")
    return "/".join(parts)


def check_bucket(settings, *, create=False):
    if not enabled(settings):
        return
    with client(settings) as connection:
        try:
            response = connection.get(f"bucket/{bucket(settings)}")
        except httpx.HTTPError:
            raise StorageUnavailable("تعذر الاتصال بتخزين الملفات. حاول مرة أخرى.") from None
        if create and response.status_code in {400, 404}:
            request(
                connection,
                "POST",
                "bucket",
                json={
                    "id": settings.rag_supabase_bucket,
                    "name": settings.rag_supabase_bucket,
                    "public": False,
                    "file_size_limit": settings.max_upload_bytes,
                },
            )
            response = request(connection, "GET", f"bucket/{bucket(settings)}")
        if not response.is_success:
            raise StorageUnavailable("حاوية الملفات غير متاحة. جهّز Supabase Storage أولًا.")
        if response.json().get("public") is not False:
            raise StorageUnavailable("يجب أن تكون حاوية ملفات Supabase خاصة.")


def upload(settings, path):
    if not enabled(settings):
        return
    key = object_key(settings, path.name)
    with client(settings) as connection, path.open("rb") as data:
        request(
            connection,
            "POST",
            f"object/{bucket(settings)}/{quote(key, safe='/')}",
            content=data,
            headers={
                "Content-Type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "x-upsert": "true",
            },
        )


def original_path(settings, directory, original):
    path = directory / original
    key = object_key(settings, original)
    if path.is_file() or not enabled(settings):
        return path
    with client(settings) as connection:
        response = request(
            connection, "GET", f"object/authenticated/{bucket(settings)}/{quote(key, safe='/')}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    # Concurrent reads must never observe a partially downloaded original.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(response.content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def delete(settings, original):
    if not enabled(settings):
        return
    with client(settings) as connection:
        request(
            connection,
            "DELETE",
            f"object/{bucket(settings)}",
            json={"prefixes": [object_key(settings, original)]},
        )


def delete_workspace(settings):
    """Remove originals for a whole owner/assistant, including orphan uploads."""
    if not enabled(settings):
        return
    # Trailing slash prevents matching sibling owners or assistant identifiers.
    prefix = object_key(settings, "placeholder").rsplit("uploads/", 1)[0]
    with client(settings) as connection:
        pending = [prefix]
        while pending:
            directory = pending.pop()
            while True:
                rows = request(
                    connection,
                    "POST",
                    f"object/list/{bucket(settings)}",
                    json={"prefix": directory, "limit": 100, "offset": 0},
                ).json()
                if not rows:
                    break
                keys = []
                for row in rows:
                    key = directory + row["name"]
                    if row.get("id") is None:
                        # Empty folders have no independent object to remove.
                        pending.append(key + "/")
                    else:
                        keys.append(key)
                if keys:
                    request(
                        connection, "DELETE", f"object/{bucket(settings)}", json={"prefixes": keys}
                    )
                if any(row.get("id") is None for row in rows):
                    # Process subdirectories before listing this parent again.
                    pending.insert(0, directory)
                    break

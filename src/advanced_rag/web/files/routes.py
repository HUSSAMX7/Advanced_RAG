"""Library, upload, indexing and source HTTP routes."""

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from ..dependencies import LibraryDependency, WorkspaceDependency
from . import object_storage, processing, services


def create_router(prefix):
    router = APIRouter(prefix=prefix, tags=["files"])

    @router.get("/files")
    async def files(library: LibraryDependency):
        return processing.list_files(library)

    @router.post("/files", status_code=201)
    async def upload(file: UploadFile, library: LibraryDependency):
        return await services.upload(file, library)

    @router.post("/files/{file_id}/train")
    async def train(file_id: str, library: LibraryDependency, workspace: WorkspaceDependency):
        row = services.train(library, file_id, require_owner_keys=workspace.require_owner_keys)
        return JSONResponse(row, status_code=200 if row["status"] == "trained" else 202)

    @router.post("/files/{file_id}/cancel")
    async def cancel(file_id: str, library: LibraryDependency):
        return await processing.cancel(library, file_id)

    @router.post("/files/{file_id}/unindex")
    async def unindex(file_id: str, library: LibraryDependency):
        return await processing.remove(library, file_id)

    @router.delete("/files/{file_id}", status_code=204)
    async def delete(file_id: str, library: LibraryDependency):
        await processing.remove(library, file_id, delete=True)
        return Response(status_code=204)

    @router.get("/files/{file_id}/download")
    async def download(file_id: str, library: LibraryDependency):
        path, filename = await object_storage.run(services.original_file, library, file_id)
        return FileResponse(path, filename=filename)

    @router.get("/sources/{chunk_id}")
    async def source(chunk_id: str, request: Request, library: LibraryDependency):
        return services.source(library, chunk_id, request.path_params.get("assistant_id"))

    @router.get("/sources/{chunk_id}/images/{image_id}")
    async def source_image(chunk_id: str, image_id: str, library: LibraryDependency):
        return FileResponse(
            processing.image(library, chunk_id, image_id),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    return router

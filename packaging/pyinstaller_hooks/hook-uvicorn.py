"""Keep the packaged backend from collecting unused uvicorn server modes."""

hiddenimports = [
    "uvicorn.config",
    "uvicorn.importer",
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.server",
]

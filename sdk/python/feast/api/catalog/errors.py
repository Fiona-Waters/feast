from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class IcebergCatalogException(Exception):
    def __init__(self, message: str, error_type: str, status_code: int):
        self.message = message
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(message)


class NamespaceNotFoundException(IcebergCatalogException):
    def __init__(self, namespace: str):
        super().__init__(
            message=f"Namespace does not exist: {namespace}",
            error_type="NoSuchNamespaceException",
            status_code=404,
        )


class NamespaceAlreadyExistsException(IcebergCatalogException):
    def __init__(self, namespace: str):
        super().__init__(
            message=f"Namespace already exists: {namespace}",
            error_type="AlreadyExistsException",
            status_code=409,
        )


class NamespaceNotEmptyException(IcebergCatalogException):
    def __init__(self, namespace: str):
        super().__init__(
            message=f"Namespace is not empty: {namespace}",
            error_type="NamespaceNotEmptyException",
            status_code=409,
        )


class TableNotFoundException(IcebergCatalogException):
    def __init__(self, namespace: str, table: str):
        super().__init__(
            message=f"Table does not exist: {namespace}.{table}",
            error_type="NoSuchTableException",
            status_code=404,
        )


class TableAlreadyExistsException(IcebergCatalogException):
    def __init__(self, namespace: str, table: str):
        super().__init__(
            message=f"Table already exists: {namespace}.{table}",
            error_type="AlreadyExistsException",
            status_code=409,
        )


class ViewNotFoundException(IcebergCatalogException):
    def __init__(self, namespace: str, view: str):
        super().__init__(
            message=f"View does not exist: {namespace}.{view}",
            error_type="NoSuchViewException",
            status_code=404,
        )


class ViewAlreadyExistsException(IcebergCatalogException):
    def __init__(self, namespace: str, view: str):
        super().__init__(
            message=f"View already exists: {namespace}.{view}",
            error_type="AlreadyExistsException",
            status_code=409,
        )


class VolumeNotFoundException(IcebergCatalogException):
    def __init__(self, namespace: str, volume: str):
        super().__init__(
            message=f"Volume does not exist: {namespace}.{volume}",
            error_type="NoSuchVolumeException",
            status_code=404,
        )


class VolumeAlreadyExistsException(IcebergCatalogException):
    def __init__(self, namespace: str, volume: str):
        super().__init__(
            message=f"Volume already exists: {namespace}.{volume}",
            error_type="AlreadyExistsException",
            status_code=409,
        )


def register_iceberg_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IcebergCatalogException)
    async def iceberg_exception_handler(
        request: Request, exc: IcebergCatalogException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.message,
                    "type": exc.error_type,
                    "code": exc.status_code,
                }
            },
        )

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app import db_models  # noqa: F401  rejestruje tabele w Base.metadata
from app.cache import JsonCache, make_redis
from app.database import Base, make_database
from app.models import GroupClass, GroupClassCreate
from app.repository import ClassRepository, Conflict, NotFound

SERVICE_NAME = "class-service"


def create_app(database_url=None, redis_client=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = make_database(
            database_url or os.getenv("DATABASE_URL", "sqlite:///./class.db")
        )
        client = None
        try:
            client = redis_client if redis_client is not None else make_redis(
                os.getenv("REDIS_URL", "redis://localhost:6379/0")
            )
            Base.metadata.create_all(engine)
            repository = ClassRepository(sessions)
            repository.seed()
            app.state.engine = engine
            app.state.redis = client
            app.state.repository = repository
            app.state.cache = JsonCache(
                client,
                prefix=os.getenv("CACHE_PREFIX", "lab2:fitness-club:class-service"),
                ttl=int(os.getenv("CACHE_TTL_SECONDS", "60")),
                resource_name="class",
            )
            yield
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                engine.dispose()

    app = FastAPI(title="Class Service", lifespan=lifespan)

    @app.exception_handler(NotFound)
    def not_found_handler(request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(Conflict)
    def conflict_handler(request: Request, exc: Conflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def repo(request: Request) -> ClassRepository:
        return request.app.state.repository

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/classes", response_model=list[GroupClass])
    def list_classes(request: Request):
        return repo(request).list_classes()

    @app.get("/classes/{class_id}", response_model=GroupClass)
    def get_class(class_id: str, request: Request, response: Response):
        cache = request.app.state.cache
        cached, source = cache.get(class_id)
        if cached is not None:
            response.headers["X-Cache"] = source
            return cached

        payload = repo(request).get_class(class_id).model_dump(mode="json")
        if source != "BYPASS" and not cache.put(class_id, payload):
            source = "BYPASS"
        response.headers["X-Cache"] = source
        return payload

    @app.post("/classes", response_model=GroupClass, status_code=201)
    def create_class(payload: GroupClassCreate, request: Request):
        return repo(request).create_class(payload)

    @app.patch("/classes/{class_id}/cancel", response_model=GroupClass)
    def cancel_class(class_id: str, request: Request):
        updated = repo(request).change_status(class_id, "cancelled")
        request.app.state.cache.delete(class_id)
        return updated

    @app.patch("/classes/{class_id}/finish", response_model=GroupClass)
    def finish_class(class_id: str, request: Request):
        updated = repo(request).change_status(class_id, "finished")
        request.app.state.cache.delete(class_id)
        return updated

    return app


app = create_app()
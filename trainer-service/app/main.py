import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app import db_models  # noqa: F401  rejestruje tabele w Base.metadata
from app.cache import JsonCache, make_redis
from app.database import Base, make_database
from app.models import (
    Availability, AvailabilityCreate, Session, SessionCreate, Trainer, TrainerCreate,
    TrainerStatusUpdate,
)
from app.repository import Conflict, NotFound, TrainerRepository

SERVICE_NAME = "trainer-service"


def create_app(database_url=None, redis_client=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = make_database(
            database_url or os.getenv("DATABASE_URL", "sqlite:///./trainer.db")
        )
        client = None
        try:
            client = redis_client if redis_client is not None else make_redis(
                os.getenv("REDIS_URL", "redis://localhost:6379/0")
            )
            Base.metadata.create_all(engine)
            repository = TrainerRepository(sessions)
            repository.seed()
            app.state.engine = engine
            app.state.redis = client
            app.state.repository = repository
            app.state.cache = JsonCache(
                client,
                prefix=os.getenv("CACHE_PREFIX", "lab2:fitness-club:trainer-service"),
                ttl=int(os.getenv("CACHE_TTL_SECONDS", "60")),
                resource_name="trainer",
            )
            yield
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                engine.dispose()

    app = FastAPI(title="Trainer Service", lifespan=lifespan)

    @app.exception_handler(NotFound)
    def not_found_handler(request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(Conflict)
    def conflict_handler(request: Request, exc: Conflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def repo(request: Request) -> TrainerRepository:
        return request.app.state.repository

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE_NAME}


    @app.get("/trainers", response_model=list[Trainer])
    def list_trainers(request: Request):
        return repo(request).list_trainers()

    @app.get("/trainers/{trainer_id}", response_model=Trainer)
    def get_trainer(trainer_id: str, request: Request, response: Response):
        cache = request.app.state.cache
        cached, source = cache.get(trainer_id)
        if cached is not None:
            response.headers["X-Cache"] = source
            return cached

        payload = repo(request).get_trainer(trainer_id).model_dump(mode="json")
        if source != "BYPASS" and not cache.put(trainer_id, payload):
            source = "BYPASS"
        response.headers["X-Cache"] = source
        return payload

    @app.post("/trainers", response_model=Trainer, status_code=201)
    def create_trainer(payload: TrainerCreate, request: Request):
        return repo(request).create_trainer(payload)

    @app.patch("/trainers/{trainer_id}/status", response_model=Trainer)
    def set_trainer_status(trainer_id: str, payload: TrainerStatusUpdate, request: Request):
        updated = repo(request).set_trainer_status(trainer_id, payload.status)
        request.app.state.cache.delete(trainer_id)
        return updated

    @app.get("/trainers/{trainer_id}/availability", response_model=list[Availability])
    def list_availability(trainer_id: str, request: Request):
        return repo(request).list_availability(trainer_id)

    @app.post("/trainers/{trainer_id}/availability", response_model=Availability, status_code=201)
    def add_availability(trainer_id: str, payload: AvailabilityCreate, request: Request):
        return repo(request).add_availability(trainer_id, payload)

    @app.get("/sessions", response_model=list[Session])
    def list_sessions(request: Request):
        return repo(request).list_sessions()

    @app.get("/sessions/{session_id}", response_model=Session)
    def get_session(session_id: str, request: Request):
        return repo(request).get_session(session_id)

    @app.post("/sessions", response_model=Session, status_code=201)
    def create_session(payload: SessionCreate, request: Request):
        return repo(request).create_session(payload)

    @app.patch("/sessions/{session_id}/cancel", response_model=Session)
    def cancel_session(session_id: str, request: Request):
        return repo(request).cancel_session(session_id)

    return app


app = create_app()

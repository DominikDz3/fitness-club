import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response

from app import db_models  # noqa: F401  rejestruje tabele w Base.metadata
from app.cache import JsonCache, make_redis
from app.database import Base, make_database
from app.models import Membership, MembershipCreate, SuspendRequest
from app.repository import MembershipConflict, MembershipNotFound, MembershipRepository

SERVICE_NAME = "membership-service"


def create_app(database_url=None, redis_client=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = make_database(
            database_url or os.getenv("DATABASE_URL", "sqlite:///./app.db")
        )
        client = None
        try:
            client = redis_client if redis_client is not None else make_redis(
                os.getenv("REDIS_URL", "redis://localhost:6379/0")
            )
            Base.metadata.create_all(engine)
            repository = MembershipRepository(sessions)
            repository.seed()
            app.state.engine = engine
            app.state.redis = client
            app.state.repository = repository
            app.state.cache = JsonCache(
                client,
                prefix=os.getenv("CACHE_PREFIX", "lab2:fitness-club:membership-service"),
                ttl=int(os.getenv("CACHE_TTL_SECONDS", "60")),
                resource_name="membership",
            )
            yield
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                engine.dispose()

    app = FastAPI(title="Membership Service", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/memberships", response_model=list[Membership])
    def list_memberships(request: Request):
        return request.app.state.repository.list()

    @app.get("/memberships/{membership_id}", response_model=Membership)
    def get_membership(membership_id: str, request: Request, response: Response):
        cache = request.app.state.cache
        cached, source = cache.get(membership_id)
        if cached is not None:
            response.headers["X-Cache"] = source
            return cached

        try:
            membership = request.app.state.repository.get(membership_id)
        except MembershipNotFound as exc:
            raise HTTPException(status_code=404, detail="Membership not found") from exc

        payload = membership.model_dump(mode="json")
        if source != "BYPASS" and not cache.put(membership_id, payload):
            source = "BYPASS"
        response.headers["X-Cache"] = source
        return payload

    @app.post("/memberships", response_model=Membership, status_code=201)
    def create_membership(payload: MembershipCreate, request: Request):
        try:
            return request.app.state.repository.create(payload)
        except MembershipConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/memberships/{membership_id}/suspend", response_model=Membership)
    def suspend_membership(membership_id: str, payload: SuspendRequest, request: Request):
        try:
            updated = request.app.state.repository.suspend(membership_id, payload.days)
        except MembershipNotFound as exc:
            raise HTTPException(status_code=404, detail="Membership not found") from exc
        except MembershipConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        request.app.state.cache.delete(membership_id)
        return updated

    @app.patch("/memberships/{membership_id}/resume", response_model=Membership)
    def resume_membership(membership_id: str, request: Request):
        try:
            updated = request.app.state.repository.resume(membership_id)
        except MembershipNotFound as exc:
            raise HTTPException(status_code=404, detail="Membership not found") from exc
        except MembershipConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        request.app.state.cache.delete(membership_id)
        return updated

    return app


app = create_app()

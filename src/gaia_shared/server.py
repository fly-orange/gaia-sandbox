import asyncio
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

from .schema import TaskRequest


def create_app(service, token):
    if not token or token == "replace-with-a-random-token":
        raise ValueError("Set a non-placeholder GAIA_SERVER_TOKEN before starting")

    @asynccontextmanager
    async def lifespan(app):
        sampler = asyncio.create_task(service.sample_server())
        try:
            yield
        finally:
            service.stop_sampling.set()
            await sampler

    app = FastAPI(title="GAIA Shared OpenHands Agent Service", lifespan=lifespan)

    def authorize(authorization):
        if not hmac.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "Invalid service token")

    @app.get("/health")
    async def health(authorization: str | None = Header(default=None)):
        authorize(authorization)
        return service.health()

    @app.post("/tasks")
    async def execute(request: TaskRequest, authorization: str | None = Header(default=None)):
        authorize(authorization)
        if service.waiting >= service.cfg.server["max_concurrency"] * 2:
            raise HTTPException(429, "Task queue full; retry after existing tasks finish")
        return await service.execute(request)

    return app

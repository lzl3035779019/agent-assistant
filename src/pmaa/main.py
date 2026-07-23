from contextlib import asynccontextmanager

from fastapi import FastAPI

from pmaa.api.routes import router
from pmaa.config import settings
from pmaa.runtime_services import (
    background_job_manager,
    daily_brief_schedule_store,
    scheduler_worker,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = scheduler_worker
    background_job_manager.store.recover_interrupted_jobs()
    if settings.automation_scheduler_enabled or daily_brief_schedule_store.has_enabled():
        scheduler_worker.start()
    try:
        yield
    finally:
        scheduler_worker.stop()
        background_job_manager.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router)

from fastapi import FastAPI

from pmaa.api.routes import router
from pmaa.config import settings


app = FastAPI(title=settings.app_name)
app.include_router(router)

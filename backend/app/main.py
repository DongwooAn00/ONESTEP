from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.env import load_project_env

load_project_env()

from app.api.routes import router

app = FastAPI(title="ONESTEP API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

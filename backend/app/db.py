from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


DEFAULT_DATABASE_URL = "postgresql://onestep:onestep@localhost:5432/onestep"


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


@contextmanager
def connect() -> Iterator[object]:
    try:
        import psycopg
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PostgreSQL 드라이버가 설치되어 있지 않습니다. "
            "`cd backend && pip install -r requirements.txt`를 실행하세요."
        ) from exc

    with psycopg.connect(database_url(), connect_timeout=5) as connection:
        yield connection

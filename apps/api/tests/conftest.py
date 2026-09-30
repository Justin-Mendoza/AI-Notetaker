import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.jwt import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def api_client():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    identity = {"owner": uuid.uuid4()}

    def database():
        with Session(engine) as session:
            yield session

    def current_user():
        return identity["owner"]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        yield client, identity
    app.dependency_overrides.clear()
    engine.dispose()

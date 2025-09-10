"""Test configuration and fixtures."""

import pytest
import tempfile
import os
import sys

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from fitness_rewards.main import app
from fitness_rewards.models.database import Base, get_db


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    # Create a temporary database file
    db_fd, db_path = tempfile.mkstemp()
    database_url = f"sqlite:///{db_path}"
    
    # Create test engine and session
    test_engine = create_engine(database_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    
    # Create tables
    Base.metadata.create_all(bind=test_engine)
    
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()
    
    # Override the dependency
    app.dependency_overrides[get_db] = override_get_db
    
    yield TestingSessionLocal
    
    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)
    app.dependency_overrides.clear()


@pytest.fixture
def client(test_db):
    """Create a test client."""
    return TestClient(app)

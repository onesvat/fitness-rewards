"""
Comprehensive tests for the Fitness Rewards API.

This test suite covers all endpoints and functions in server.py, including:
- Authentication
- Database operations
- Balance management
- Transaction tracking
- Error handling
- Edge cases
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, date, timedelta
from freezegun import freeze_time
import json
import tempfile
import os

# Import the app and dependencies from the new structure
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fitness_rewards.main import app
from fitness_rewards.models.database import (
    get_db, Base, Balance, Transaction, ChatRegistration
)
from fitness_rewards.api.auth import verify_api_key
from fitness_rewards.config import API_KEY


# Test database setup
@pytest.fixture(scope="function")
def test_db():
    """Create a test database for each test function."""
    # Create a temporary database file
    db_fd, db_path = tempfile.mkstemp()
    test_database_url = f"sqlite:///{db_path}"
    
    # Create test engine and session
    test_engine = create_engine(test_database_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    
    # Create all tables
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
    app.dependency_overrides.clear()
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(test_db):
    """Create a test client with the test database."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Return headers with valid API key."""
    return {"x-api-key": API_KEY}


@pytest.fixture
def db_session(test_db):
    """Get a database session for direct database operations."""
    session = test_db()
    try:
        yield session
    finally:
        session.close()


class TestAuthentication:
    """Test API key authentication."""
    
    def test_valid_api_key(self, client, auth_headers):
        """Test that valid API key allows access."""
        response = client.get("/balance", headers=auth_headers)
        assert response.status_code == 200
    
    def test_missing_api_key(self, client):
        """Test that missing API key returns 422."""
        response = client.get("/balance")
        assert response.status_code == 422
    
    def test_invalid_api_key(self, client):
        """Test that invalid API key returns 401."""
        response = client.get("/balance", headers={"x-api-key": "invalid-key"})
        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]



class TestBalanceEndpoint:
    """Test the /balance endpoint."""
    
    def test_get_balance_exists(self, client, auth_headers, db_session):
        """Test getting balance when it exists."""
        balance = Balance(total_points=100)
        db_session.add(balance)
        db_session.commit()
        
        response = client.get("/balance", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["balance"] == 100
        assert "last_updated" in data
    
    def test_get_balance_not_exists(self, client, auth_headers):
        """Test getting balance when it doesn't exist."""
        response = client.get("/balance", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["balance"] == 0
        assert "No balance record found" in data["message"]


class TestWithdrawEndpoint:
    """Test the /withdraw endpoint."""
    
    def test_successful_withdrawal(self, client, auth_headers, db_session):
        """Test successful point withdrawal."""
        balance = Balance(total_points=100)
        db_session.add(balance)
        db_session.commit()
        
        params = {"name": "gaming", "count": 30}
        response = client.get("/withdraw", params=params, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["withdrawn"] == 30
        assert data["balance_remaining"] == 70
        
        # Verify database updates
        updated_balance = db_session.query(Balance).first()
        assert updated_balance.total_points == 70
        
        # Verify transaction record
        transaction = db_session.query(Transaction).filter_by(type="withdraw").first()
        assert transaction is not None
        assert transaction.name == "gaming"
        assert transaction.count == 30
        assert transaction.balance_after == 70
    
    def test_insufficient_balance(self, client, auth_headers, db_session):
        """Test withdrawal with insufficient balance."""
        balance = Balance(total_points=10)
        db_session.add(balance)
        db_session.commit()
        
        params = {"name": "gaming", "count": 20}
        response = client.get("/withdraw", params=params, headers=auth_headers)
        
        assert response.status_code == 400
        assert "Insufficient balance" in response.json()["detail"]
    
    def test_withdraw_zero_points(self, client, auth_headers, db_session):
        """Test that withdrawing zero points fails."""
        balance = Balance(total_points=100)
        db_session.add(balance)
        db_session.commit()
        
        params = {"name": "gaming", "count": 0}
        response = client.get("/withdraw", params=params, headers=auth_headers)
        
        assert response.status_code == 400
        assert "Count must be greater than 0" in response.json()["detail"]
    
    def test_withdraw_negative_points(self, client, auth_headers, db_session):
        """Test that withdrawing negative points fails."""
        balance = Balance(total_points=100)
        db_session.add(balance)
        db_session.commit()
        
        params = {"name": "gaming", "count": -10}
        response = client.get("/withdraw", params=params, headers=auth_headers)
        
        assert response.status_code == 400
        assert "Count must be greater than 0" in response.json()["detail"]
    
    def test_withdraw_no_balance_record(self, client, auth_headers):
        """Test withdrawal when no balance record exists."""
        params = {"name": "gaming", "count": 10}
        response = client.get("/withdraw", params=params, headers=auth_headers)
        
        assert response.status_code == 400
        assert "Insufficient balance" in response.json()["detail"]


class TestDepositEndpoint:
    """Test the /deposit endpoint."""
    
    def test_successful_deposit_existing_balance(self, client, auth_headers, db_session):
        """Test successful deposit to existing balance."""
        balance = Balance(total_points=50)
        db_session.add(balance)
        db_session.commit()
        
        params = {"name": "manual_bonus", "count": 25}
        response = client.get("/deposit", params=params, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["deposited"] == 25
        assert data["balance_total"] == 75
        
        # Verify database updates
        updated_balance = db_session.query(Balance).first()
        assert updated_balance.total_points == 75
        
        # Verify transaction record
        transaction = db_session.query(Transaction).filter_by(type="deposit").first()
        assert transaction is not None
        assert transaction.name == "manual_bonus"
        assert transaction.count == 25
        assert transaction.balance_after == 75
    
    def test_successful_deposit_no_balance(self, client, auth_headers, db_session):
        """Test successful deposit when no balance exists."""
        params = {"name": "initial_bonus", "count": 100}
        response = client.get("/deposit", params=params, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["balance_total"] == 100
        
        # Verify balance was created
        balance = db_session.query(Balance).first()
        assert balance is not None
        assert balance.total_points == 100
    
    def test_deposit_zero_points(self, client, auth_headers):
        """Test that depositing zero points fails."""
        params = {"name": "bonus", "count": 0}
        response = client.get("/deposit", params=params, headers=auth_headers)
        
        assert response.status_code == 400
        assert "Count must be greater than 0" in response.json()["detail"]
    
    def test_deposit_negative_points(self, client, auth_headers):
        """Test that depositing negative points fails."""
        params = {"name": "bonus", "count": -10}
        response = client.get("/deposit", params=params, headers=auth_headers)
        
        assert response.status_code == 400
        assert "Count must be greater than 0" in response.json()["detail"]


class TestTransactionsEndpoint:
    """Test the /transactions endpoint."""
    
    def setup_sample_transactions(self, db_session):
        """Create sample transaction data."""
        transactions = [
            Transaction(type="deposit", name="workout", count=10, balance_after=10, 
                       timestamp=datetime(2024, 1, 15, 10, 0, 0)),
            Transaction(type="withdraw", name="gaming", count=5, balance_after=5, 
                       timestamp=datetime(2024, 1, 15, 11, 0, 0)),
            Transaction(type="deposit", name="bonus", count=20, balance_after=25, 
                       timestamp=datetime(2024, 1, 15, 12, 0, 0)),
            Transaction(type="withdraw", name="tv", count=10, balance_after=15, 
                       timestamp=datetime(2024, 1, 15, 13, 0, 0)),
        ]
        
        for transaction in transactions:
            db_session.add(transaction)
        db_session.commit()
    
    def test_get_all_transactions(self, client, auth_headers, db_session):
        """Test getting all transactions."""
        self.setup_sample_transactions(db_session)
        
        response = client.get("/transactions", headers=auth_headers)
        
        assert response.status_code == 200
        transactions = response.json()
        assert len(transactions) == 4
        
        # Should be ordered by timestamp descending
        assert transactions[0]["timestamp"] > transactions[1]["timestamp"]
    
    def test_get_transactions_with_limit(self, client, auth_headers, db_session):
        """Test getting transactions with limit."""
        self.setup_sample_transactions(db_session)
        
        params = {"limit": 2}
        response = client.get("/transactions", params=params, headers=auth_headers)
        
        assert response.status_code == 200
        transactions = response.json()
        assert len(transactions) == 2
    
    def test_get_transactions_filter_by_type(self, client, auth_headers, db_session):
        """Test filtering transactions by type."""
        self.setup_sample_transactions(db_session)
        
        # Test deposit filter
        params = {"type": "deposit"}
        response = client.get("/transactions", params=params, headers=auth_headers)
        
        assert response.status_code == 200
        transactions = response.json()
        assert len(transactions) == 2  # Two deposits
        assert all(t["type"] == "deposit" for t in transactions)
        
        # Test withdraw filter
        params = {"type": "withdraw"}
        response = client.get("/transactions", params=params, headers=auth_headers)
        
        assert response.status_code == 200
        transactions = response.json()
        assert len(transactions) == 2  # Two withdrawals
        assert all(t["type"] == "withdraw" for t in transactions)
    
    def test_get_transactions_no_data(self, client, auth_headers):
        """Test getting transactions when none exist."""
        response = client.get("/transactions", headers=auth_headers)
        
        assert response.status_code == 200
        transactions = response.json()
        assert transactions == []


class TestHealthEndpoint:
    """Test the /health endpoint."""
    
    def test_health_check(self, client):
        """Test that health endpoint returns healthy status."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestIntegrationScenarios:
    """Test complete workflow scenarios."""
    
    def test_complete_balance_flow(self, client, auth_headers, db_session):
        """Test a complete balance management flow."""
        # 1. Check initial balance (should be 0)
        response = client.get("/balance", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["balance"] == 0
        
        # 2. Deposit some points manually
        params = {"name": "bonus", "count": 100}
        response = client.get("/deposit", params=params, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["balance_total"] == 100
        
        # 3. Check balance after deposit
        response = client.get("/balance", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["balance"] == 100
        
        # 4. Withdraw some points
        params = {"name": "gaming", "count": 30}
        response = client.get("/withdraw", params=params, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["balance_remaining"] == 70
        
        # 5. Deposit more points
        params = {"name": "reward", "count": 25}
        response = client.get("/deposit", params=params, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["balance_total"] == 95
        
        # 6. Check transactions (should have 3 total: 2 deposits, 1 withdrawal)
        response = client.get("/transactions", headers=auth_headers)
        assert response.status_code == 200
        transactions = response.json()
        assert len(transactions) == 3
        
        # Verify transaction types
        deposit_transactions = [t for t in transactions if t["type"] == "deposit"]
        withdraw_transactions = [t for t in transactions if t["type"] == "withdraw"]
        assert len(deposit_transactions) == 2
        assert len(withdraw_transactions) == 1
        
        # 7. Final balance check
        response = client.get("/balance", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["balance"] == 95
    
    def test_time_sensitive_operations(self, client, auth_headers, db_session):
        """Test operations that depend on time."""
        # Test transaction timestamps
        with freeze_time("2024-01-15 10:00:00"):
            params = {"name": "bonus", "count": 50}
            response = client.get("/deposit", params=params, headers=auth_headers)
            assert response.status_code == 200
        
        # Move time forward and make another transaction
        with freeze_time("2024-01-15 11:00:00"):
            params = {"name": "gaming", "count": 20}
            response = client.get("/withdraw", params=params, headers=auth_headers)
            assert response.status_code == 200
        
        # Check that transactions have correct timestamps
        response = client.get("/transactions", headers=auth_headers)
        assert response.status_code == 200
        transactions = response.json()
        
        # Should have 2 transactions with different timestamps
        assert len(transactions) == 2
        
        # Transactions should be ordered by timestamp descending (newest first)
        timestamps = [t["timestamp"] for t in transactions]
        assert timestamps[0] > timestamps[1]  # First transaction is newer


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_database_connection_error(self, client, auth_headers, mocker):
        """Test handling of database connection errors."""
        # Mock database session to raise an exception
        def mock_get_db():
            raise Exception("Database connection failed")
        
        app.dependency_overrides[get_db] = mock_get_db
        
        try:
            response = client.get("/balance", headers=auth_headers)
            # FastAPI will return 500 for unhandled exceptions
            assert response.status_code == 500
        except Exception as e:
            # The exception is expected to bubble up in test client
            assert "Database connection failed" in str(e)
        finally:
            # Cleanup
            app.dependency_overrides.clear()
    
    def test_concurrent_balance_operations(self, client, auth_headers, db_session):
        """Test concurrent balance operations."""
        # Initialize balance
        balance = Balance(total_points=100)
        db_session.add(balance)
        db_session.commit()
        
        # Simulate concurrent withdrawals
        # In a real scenario, you might use threading, but for testing we'll do sequential
        params1 = {"name": "activity1", "count": 30}
        params2 = {"name": "activity2", "count": 40}
        
        response1 = client.get("/withdraw", params=params1, headers=auth_headers)
        response2 = client.get("/withdraw", params=params2, headers=auth_headers)
        
        # Both should succeed
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Final balance should be correct
        response = client.get("/balance", headers=auth_headers)
        assert response.json()["balance"] == 30  # 100 - 30 - 40


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Database models for the Fitness Rewards API."""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

try:
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base
    Base = declarative_base()

from ..config import DATABASE_URL

# Database setup
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Balance(Base):
    """Balance table for point credits."""
    __tablename__ = "balance"

    id = Column(Integer, primary_key=True, index=True)
    total_points = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Transaction(Base):
    """Transaction table for tracking deposits and withdrawals."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    type = Column(String, index=True)  # 'deposit' or 'withdraw'
    name = Column(String, index=True)  # activity name or source
    count = Column(Integer)
    balance_after = Column(Integer)
    description = Column(String, nullable=True)


class ChatRegistration(Base):
    """Chat registration table for Telegram notifications."""
    __tablename__ = "chat_registrations"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, unique=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_notification = Column(DateTime, nullable=True)
    is_active = Column(Integer, default=1)  # 1 for active, 0 for inactive


def get_db():
    """Dependency to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """Initialize the database and create tables."""
    Base.metadata.create_all(bind=engine)
    
    # Initialize balance if it doesn't exist
    db = SessionLocal()
    try:
        balance = db.query(Balance).first()
        if not balance:
            balance = Balance(total_points=0)
            db.add(balance)
            db.commit()
            print("Initialized balance with 0 points")
    finally:
        db.close()

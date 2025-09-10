
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Query, Header
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, func
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, date, timezone
from typing import Optional
from contextlib import asynccontextmanager

# --- Configuration ---
DATABASE_URL = "sqlite:///./fitness_rewards.db"
API_KEY = "your-secret-api-key-123"  # Change this to a secure key

# --- Database Setup ---
try:
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base
    Base = declarative_base()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Define the database table model for workout events
class WorkoutEvent(Base):
    __tablename__ = "workout_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    device_id = Column(String, index=True)
    workout_id = Column(BigInteger, index=True)
    event = Column(String, index=True)
    count = Column(Integer, nullable=True)

# Define the balance table for point credits
class Balance(Base):
    __tablename__ = "balance"

    id = Column(Integer, primary_key=True, index=True)
    total_points = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

# Define the transaction table for tracking deposits and withdrawals
class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    type = Column(String, index=True)  # 'deposit' or 'withdraw'
    name = Column(String, index=True)  # activity name or source
    count = Column(Integer)
    balance_after = Column(Integer)
    description = Column(String, nullable=True)

# Dependency to get a DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Authentication dependency
def verify_api_key(x_api_key: str = Header(..., description="API Key for authentication")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    # Startup
    print("Creating database and tables...")
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
    
    print("Database setup complete.")
    
    yield
    
    # Shutdown (if needed)
    print("Application shutting down...")

# --- FastAPI Application ---
app = FastAPI(
    title="Fitness Rewards API",
    description="Receives and analyzes workout data from an ESP32 device.",
    lifespan=lifespan
)

@app.get("/webhook", tags=["Data Ingestion"])
def receive_webhook(
    deviceId: str = Query(..., description="Unique identifier for the ESP32 device."),
    workoutId: int = Query(..., description="Timestamp-based unique ID for the workout session."),
    event: str = Query(..., description="The type of event (e.g., 'started', 'paused', 'stopped', 'revolution_add')."),
    count: Optional[int] = Query(None, description="The number of revolutions to add (only for 'revolution_add' event)."),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Listens for GET requests from the ESP32 device, validates the data,
    and logs the workout event to the SQLite database.
    """
    print(f"Received event: deviceId={deviceId}, workoutId={workoutId}, event={event}, count={count}")

    valid_events = ["started", "paused", "resumed", "stopped", "revolution_add"]
    if event not in valid_events:
        raise HTTPException(status_code=400, detail=f"Invalid event type. Must be one of {valid_events}")

    if event == "revolution_add" and count is None:
        raise HTTPException(status_code=400, detail="The 'count' parameter is required for 'revolution_add' events.")

    db_event = WorkoutEvent(
        device_id=deviceId,
        workout_id=workoutId,
        event=event,
        count=count
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    # Auto-deposit points to balance when revolution_add events occur
    if event == "revolution_add" and count:
        balance = db.query(Balance).first()
        if balance:
            balance.total_points += count
            balance.updated_at = datetime.now(timezone.utc)
            
            # Record the transaction
            transaction = Transaction(
                type="deposit",
                name="workout",
                count=count,
                balance_after=balance.total_points,
                description=f"Auto-deposit from workout {workoutId}"
            )
            db.add(transaction)
            db.commit()
            print(f"Auto-deposited {count} points to balance. New balance: {balance.total_points}")

    return {"status": "success", "message": "Event logged successfully", "logged_event_id": db_event.id}

@app.get("/workouts", tags=["Analytics"])
def get_workouts(
    start_date: date = Query(..., description="The start date for the query range (YYYY-MM-DD)."),
    end_date: Optional[date] = Query(None, description="The optional end date for the query range (YYYY-MM-DD). Defaults to today."),
    device_id: Optional[str] = Query(None, description="Optional device ID to filter workouts."),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Returns workout data within a given date range, optionally filtered by device_id.
    Returns a JSON array of workout sessions with aggregated data.
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc).date()

    # Convert dates to datetimes to ensure a full day range
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())

    # Build query with date range filter
    query = db.query(WorkoutEvent).filter(
        WorkoutEvent.timestamp >= start_datetime,
        WorkoutEvent.timestamp <= end_datetime
    )
    
    # Add device_id filter if provided
    if device_id:
        query = query.filter(WorkoutEvent.device_id == device_id)
    
    # Execute query and get all matching events
    events = query.order_by(WorkoutEvent.workout_id, WorkoutEvent.timestamp).all()
    
    # Group events by workout_id and aggregate data
    workouts = {}
    for event in events:
        workout_id = event.workout_id
        
        if workout_id not in workouts:
            workouts[workout_id] = {
                "workout_id": workout_id,
                "device_id": event.device_id,
                "start_datetime": None,
                "end_datetime": None,
                "duration": None,
                "cycles": 0
            }
        
        # Track start and end times
        if event.event == "started":
            workouts[workout_id]["start_datetime"] = event.timestamp.isoformat()
        elif event.event == "stopped":
            workouts[workout_id]["end_datetime"] = event.timestamp.isoformat()
        
        # Sum revolution counts
        if event.event == "revolution_add" and event.count:
            workouts[workout_id]["cycles"] += event.count
    
    # Calculate duration for completed workouts
    for workout in workouts.values():
        if workout["start_datetime"] and workout["end_datetime"]:
            start = datetime.fromisoformat(workout["start_datetime"])
            end = datetime.fromisoformat(workout["end_datetime"])
            duration_seconds = (end - start).total_seconds()
            workout["duration"] = int(duration_seconds)  # Duration in seconds
    
    return list(workouts.values())

@app.get("/balance", tags=["Balance"])
def get_balance(
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Returns the current point balance.
    """
    balance = db.query(Balance).first()
    if not balance:
        return {"balance": 0, "message": "No balance record found"}
    
    return {
        "balance": balance.total_points,
        "last_updated": balance.updated_at.isoformat()
    }

@app.get("/withdraw", tags=["Balance"])
def withdraw_points(
    name: str = Query(..., description="Name of the activity consuming points (e.g., 'watching_tv', 'gaming')."),
    count: int = Query(..., description="Number of points to withdraw."),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Withdraws points from the balance for a named activity.
    """
    if count <= 0:
        raise HTTPException(status_code=400, detail="Count must be greater than 0")
    
    balance = db.query(Balance).first()
    if not balance or balance.total_points < count:
        current_balance = balance.total_points if balance else 0
        raise HTTPException(
            status_code=400, 
            detail=f"Insufficient balance. Current: {current_balance}, Requested: {count}"
        )
    
    # Perform withdrawal
    balance.total_points -= count
    balance.updated_at = datetime.now(timezone.utc)
    
    # Record the transaction
    transaction = Transaction(
        type="withdraw",
        name=name,
        count=count,
        balance_after=balance.total_points,
        description=f"Withdrawal for {name}"
    )
    db.add(transaction)
    db.commit()
    
    return {
        "status": "success",
        "message": f"Withdrew {count} points for {name}",
        "withdrawn": count,
        "balance_remaining": balance.total_points
    }

@app.get("/deposit", tags=["Balance"])
def deposit_points(
    name: str = Query(..., description="Name of the source adding points (e.g., 'manual_bonus', 'reward')."),
    count: int = Query(..., description="Number of points to deposit."),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Manually deposits points to the balance from a named source.
    """
    if count <= 0:
        raise HTTPException(status_code=400, detail="Count must be greater than 0")
    
    balance = db.query(Balance).first()
    if not balance:
        # Create balance if it doesn't exist
        balance = Balance(total_points=count)
        db.add(balance)
    else:
        balance.total_points += count
        balance.updated_at = datetime.now(timezone.utc)
    
    # Record the transaction
    transaction = Transaction(
        type="deposit",
        name=name,
        count=count,
        balance_after=balance.total_points,
        description=f"Manual deposit from {name}"
    )
    db.add(transaction)
    db.commit()
    
    return {
        "status": "success",
        "message": f"Deposited {count} points from {name}",
        "deposited": count,
        "balance_total": balance.total_points
    }

@app.get("/transactions", tags=["Balance"])
def get_transactions(
    limit: int = Query(10, description="Maximum number of transactions to return."),
    type: Optional[str] = Query(None, description="Filter by transaction type: 'deposit' or 'withdraw'."),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Returns recent transactions with optional filtering.
    """
    query = db.query(Transaction).order_by(Transaction.timestamp.desc())
    
    if type and type in ["deposit", "withdraw"]:
        query = query.filter(Transaction.type == type)
    
    transactions = query.limit(limit).all()
    
    transaction_list = []
    for t in transactions:
        transaction_list.append({
            "id": t.id,
            "timestamp": t.timestamp.isoformat(),
            "type": t.type,
            "name": t.name,
            "count": t.count,
            "balance_after": t.balance_after,
            "description": t.description
        })
    
    return transaction_list

# --- Main Execution ---
if __name__ == "__main__":
    print("Starting FastAPI server...")
    # To run this server, use the command: uvicorn server:app --host 0.0.0.0 --port 8000 --reload
    uvicorn.run(app, host="0.0.0.0", port=8000)

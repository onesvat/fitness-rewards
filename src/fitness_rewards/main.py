"""Main FastAPI application for Fitness Rewards API."""

import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from .config import HOST, PORT
from .models.database import (
    get_db, init_database, Balance, Transaction, ChatRegistration
)
from .api.auth import verify_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    # Startup
    print("Creating database and tables...")
    init_database()
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


@app.get("/balance", tags=["Balance"])
def get_balance(
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """Returns the current point balance."""
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
    """Withdraws points from the balance for a named activity."""
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
    """Manually deposits points to the balance from a named source."""
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
    """Returns recent transactions with optional filtering."""
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


@app.post("/register_chat", tags=["Telegram"])
def register_chat(
    chat_id: int = Query(..., description="Telegram chat ID"),
    username: Optional[str] = Query(None, description="Telegram username"),
    first_name: Optional[str] = Query(None, description="User's first name"),
    last_name: Optional[str] = Query(None, description="User's last name"),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """Register a Telegram chat for notifications."""
    # Check if chat is already registered
    existing_chat = db.query(ChatRegistration).filter(ChatRegistration.chat_id == chat_id).first()
    
    if existing_chat:
        # Update existing registration
        existing_chat.username = username
        existing_chat.first_name = first_name
        existing_chat.last_name = last_name
        existing_chat.is_active = 1
        existing_chat.registered_at = datetime.now(timezone.utc)
        message = "Chat registration updated"
    else:
        # Create new registration
        new_chat = ChatRegistration(
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        )
        db.add(new_chat)
        message = "Chat registered successfully"
    
    db.commit()
    
    return {
        "status": "success",
        "message": message,
        "chat_id": chat_id
    }


@app.get("/registered_chats", tags=["Telegram"])
def get_registered_chats(
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """Get all registered Telegram chats."""
    chats = db.query(ChatRegistration).filter(ChatRegistration.is_active == 1).all()
    
    chat_list = []
    for chat in chats:
        chat_list.append({
            "chat_id": chat.chat_id,
            "username": chat.username,
            "first_name": chat.first_name,
            "last_name": chat.last_name,
            "registered_at": chat.registered_at.isoformat(),
            "last_notification": chat.last_notification.isoformat() if chat.last_notification else None
        })
    
    return chat_list


@app.get("/health", tags=["System"])
def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


def main():
    """Main entry point for the application."""
    print("Starting FastAPI server...")
    print(f"Host: {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()

"""Main FastAPI application for Fitness Rewards API."""

import os
import uvicorn
import httpx
import asyncio
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from .config import HOST, PORT
from .models.database import (
    get_db, init_database, Balance, Transaction, ChatRegistration
)
from .api.auth import verify_api_key

# Configuration for low balance notifications
LOW_BALANCE_THRESHOLD = int(os.getenv("LOW_BALANCE_THRESHOLD", "50"))  # points
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else None

async def send_low_balance_notification(current_balance: int, db: Session):
    """Send low balance notification to all registered chats."""
    if not TELEGRAM_BOT_TOKEN:
        print("Warning: TELEGRAM_BOT_TOKEN not set, skipping low balance notification")
        return
    
    try:
        # Get all registered chats
        registered_chats = db.query(ChatRegistration).filter(ChatRegistration.is_active == 1).all()
        
        if not registered_chats:
            print("No registered chats found for low balance notification")
            return
        
        # Create the notification message
        message = f"⚠️ **Low Balance Alert** ⚠️\n\n💰 Current Balance: **{current_balance}** points\n📉 Below threshold of {LOW_BALANCE_THRESHOLD} points\n\n💪 Time to earn some more points!"
        
        # Send to each registered chat
        successful_sends = 0
        async with httpx.AsyncClient() as client:
            for chat in registered_chats:
                try:
                    response = await client.post(
                        f"{TELEGRAM_API_URL}/sendMessage",
                        json={
                            "chat_id": chat.chat_id,
                            "text": message,
                            "parse_mode": "Markdown"
                        },
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        successful_sends += 1
                        print(f"Low balance notification sent to chat {chat.chat_id}")
                    else:
                        print(f"Failed to send low balance notification to chat {chat.chat_id}: HTTP {response.status_code}")
                        
                        # Try without markdown as fallback
                        fallback_message = message.replace('*', '').replace('_', '')
                        fallback_response = await client.post(
                            f"{TELEGRAM_API_URL}/sendMessage",
                            json={
                                "chat_id": chat.chat_id,
                                "text": fallback_message
                            },
                            timeout=10.0
                        )
                        
                        if fallback_response.status_code == 200:
                            successful_sends += 1
                            print(f"Low balance notification sent to chat {chat.chat_id} (fallback)")
                        
                except Exception as e:
                    print(f"Error sending low balance notification to chat {chat.chat_id}: {e}")
        
        print(f"Low balance notification sent to {successful_sends}/{len(registered_chats)} registered chats")
        
    except Exception as e:
        print(f"Error in send_low_balance_notification: {e}")

def check_if_first_time_below_threshold(previous_balance: int, current_balance: int) -> bool:
    """Check if this is the first time balance has dropped below threshold."""
    # Check if we just crossed the threshold
    # Previous balance was >= threshold AND current balance is < threshold
    return previous_balance >= LOW_BALANCE_THRESHOLD and current_balance < LOW_BALANCE_THRESHOLD


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
async def withdraw_points(
    background_tasks: BackgroundTasks,
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
    
    # Store the previous balance before withdrawal
    previous_balance = balance.total_points
    
    # Perform withdrawal
    balance.total_points -= count
    balance.updated_at = datetime.now(timezone.utc)
    new_balance = balance.total_points
    
    # Record the transaction
    transaction = Transaction(
        type="withdraw",
        name=name,
        count=count,
        balance_after=new_balance,
        description=f"Withdrawal for {name}"
    )
    db.add(transaction)
    db.commit()
    
    # Check if we need to send low balance notification
    if check_if_first_time_below_threshold(previous_balance, new_balance):
        # Send notification in background to avoid blocking the response
        background_tasks.add_task(send_low_balance_notification, new_balance, db)
    
    return {
        "status": "success",
        "message": f"Withdrew {count} points for {name}",
        "withdrawn": count,
        "balance": new_balance
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
        "balance": balance.total_points
    }


@app.get("/transactions", tags=["Balance"])
def get_transactions(
    limit: int = Query(10, description="Maximum number of transactions to return."),
    type: Optional[str] = Query(None, description="Filter by transaction type: 'deposit' or 'withdraw'."),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering transactions (ISO format)."),
    end_date: Optional[datetime] = Query(None, description="End date for filtering transactions (ISO format)."),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """Returns recent transactions with optional filtering."""
    query = db.query(Transaction).order_by(Transaction.timestamp.desc())
    
    if type and type in ["deposit", "withdraw"]:
        query = query.filter(Transaction.type == type)
    
    if start_date:
        query = query.filter(Transaction.timestamp >= start_date)
    
    if end_date:
        query = query.filter(Transaction.timestamp <= end_date)
    
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


@app.post("/unregister_chat", tags=["Telegram"])
def unregister_chat(
    chat_id: int = Query(..., description="Telegram chat ID"),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """Unregister a Telegram chat from notifications."""
    # Find the existing chat registration
    existing_chat = db.query(ChatRegistration).filter(ChatRegistration.chat_id == chat_id).first()
    
    if not existing_chat:
        return {
            "status": "error",
            "message": "Chat not found or already unregistered",
            "chat_id": chat_id
        }
    
    if existing_chat.is_active == 0:
        return {
            "status": "info",
            "message": "Chat is already unregistered",
            "chat_id": chat_id
        }
    
    # Mark as inactive instead of deleting to preserve history
    existing_chat.is_active = 0
    db.commit()
    
    return {
        "status": "success",
        "message": "Chat unregistered successfully",
        "chat_id": chat_id
    }


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

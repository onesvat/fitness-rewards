#!/usr/bin/env python3
"""
Telegram Bot for Fitness Rewards System

This bot provides an interface to interact with the fitness rewards server
through Telegram commands.
"""

import os
import asyncio
import logging
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "your-secret-api-key-123")
BALANCE_MONITORING_ENABLED = os.getenv("BALANCE_MONITORING_ENABLED", "true").lower() == "true"
BALANCE_CHECK_INTERVAL = int(os.getenv("BALANCE_CHECK_INTERVAL", "5"))  # seconds
LOW_BALANCE_THRESHOLD = int(os.getenv("LOW_BALANCE_THRESHOLD", "50"))  # points
MAX_TRANSACTIONS_IN_NOTIFICATION = int(os.getenv("MAX_TRANSACTIONS_IN_NOTIFICATION", "3"))  # number of transactions

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

# Global variables for notification management
last_notification_messages: Dict[int, Dict[str, Any]] = {}
last_known_balance: Optional[int] = None
monitoring_task: Optional[asyncio.Task] = None
low_balance_warning_sent: bool = False

class FitnessRewardsAPI:
    """API client for the fitness rewards server."""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}
    
    async def get_balance(self) -> Dict[str, Any]:
        """Get current balance."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/balance",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def withdraw_points(self, name: str, count: int) -> Dict[str, Any]:
        """Withdraw points."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/withdraw",
                params={"name": name, "count": count},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def deposit_points(self, name: str, count: int) -> Dict[str, Any]:
        """Deposit points."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/deposit",
                params={"name": name, "count": count},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_transactions(self, limit: int = 10, transaction_type: Optional[str] = None) -> list:
        """Get recent transactions."""
        async with httpx.AsyncClient() as client:
            params = {"limit": limit}
            if transaction_type:
                params["type"] = transaction_type
            
            response = await client.get(
                f"{self.base_url}/transactions",
                params=params,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_registered_chats(self) -> list:
        """Get list of registered chats."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/registered_chats",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def register_chat(self, chat_id: int, username: str = None, 
                          first_name: str = None, last_name: str = None) -> Dict[str, Any]:
        """Register a chat for notifications."""
        async with httpx.AsyncClient() as client:
            params = {"chat_id": chat_id}
            if username:
                params["username"] = username
            if first_name:
                params["first_name"] = first_name
            if last_name:
                params["last_name"] = last_name
            
            response = await client.post(
                f"{self.base_url}/register_chat",
                params=params,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def unregister_chat(self, chat_id: int) -> Dict[str, Any]:
        """Unregister a chat from notifications."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/unregister_chat",
                params={"chat_id": chat_id},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

# Initialize API client
api = FitnessRewardsAPI(SERVER_URL, API_KEY)

def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown formatting."""
    if not text:
        return text
    # Escape characters that have special meaning in Markdown
    special_chars = ['*', '_', '[', ']', '(', ')', '`', '~']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    welcome_text = """
🏃‍♂️ **Welcome to Fitness Rewards Bot!** 🏃‍♀️

This bot helps you manage your fitness reward points. Here are the available commands:

🔹 `/balance` - Check your current point balance
🔹 `/status` - Get detailed balance and activity status
🔹 `/withdraw {amount}` - Withdraw points for activities (e.g., `/withdraw 50`)
🔹 `/deposit {amount}` - Add points manually (e.g., `/deposit 100`)
🔹 `/transactions` - View recent transaction history
🔹 `/register` - Register for balance change notifications
🔹 `/unregister` - Unregister from balance change notifications
🔹 `/monitoring` - Check balance monitoring status
🔹 `/help` - Show this help message

**Examples:**
• `/withdraw 30` - Withdraw 30 points for watching TV
• `/deposit 50` - Add 50 points as a bonus
• `/transactions` - See your last 10 transactions

Get started by typing `/balance` to see your current points!
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help message."""
    await start(update, context)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the chat for notifications."""
    try:
        chat_id = update.effective_chat.id
        user = update.effective_user
        
        result = await api.register_chat(
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        await update.message.reply_text(
            f"✅ {result['message']}\n\n"
            "You will now receive notifications when your balance changes!"
        )
        
    except Exception as e:
        logger.error(f"Error registering chat: {e}")
        await update.message.reply_text(
            "❌ Failed to register for notifications. Please try again later."
        )

async def unregister(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unregister the chat from notifications."""
    try:
        chat_id = update.effective_chat.id
        
        result = await api.unregister_chat(chat_id=chat_id)
        
        if result['status'] == 'success':
            await update.message.reply_text(
                f"✅ {result['message']}\n\n"
                "You will no longer receive balance change notifications.\n"
                "You can use `/register` again anytime to re-enable notifications."
            )
        elif result['status'] == 'info':
            await update.message.reply_text(
                f"ℹ️ {result['message']}\n\n"
                "Use `/register` if you want to enable notifications."
            )
        else:
            await update.message.reply_text(
                f"⚠️ {result['message']}"
            )
        
    except Exception as e:
        logger.error(f"Error unregistering chat: {e}")
        await update.message.reply_text(
            "❌ Failed to unregister from notifications. Please try again later."
        )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get current balance."""
    try:
        result = await api.get_balance()
        balance_amount = result.get('balance', 0)
        last_updated = result.get('last_updated', 'Unknown')
        
        # Parse and format the timestamp
        try:
            dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
            formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        except:
            formatted_time = last_updated
        
        message = f"💰 **Current Balance:** {balance_amount} points\n📅 **Last Updated:** {formatted_time}"
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
        await update.message.reply_text(
            "❌ Failed to get balance. Please try again later."
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get detailed status including balance, recent transactions, and monitoring."""
    try:
        # Get balance
        balance_result = await api.get_balance()
        balance_amount = balance_result.get('balance', 0)
        last_updated = balance_result.get('last_updated', 'Unknown')
        
        # Format timestamp
        try:
            dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
            formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        except:
            formatted_time = last_updated
        
        # Get recent transactions
        recent_transactions = await api.get_transactions(limit=5)
        
        # Build status message (escape special characters for Markdown)
        status_message = "📊 *Fitness Rewards Status* 📊\n\n"
        status_message += f"💰 *Current Balance:* {balance_amount} points\n"
        status_message += f"📅 *Last Updated:* {formatted_time}\n"
        
        # Add balance status
        if balance_amount <= 0:
            status_message += "🚫 *Status:* OUT OF POINTS!\n"
        elif balance_amount <= LOW_BALANCE_THRESHOLD:
            status_message += "⚠️ *Status:* LOW BALANCE WARNING\n"
        else:
            status_message += "✅ *Status:* Good balance\n"
        
        # Add recent activity
        if recent_transactions:
            status_message += "\n📋 *Recent Activity (Last 5):*\n"
            for transaction in recent_transactions:
                # Format timestamp
                try:
                    dt = datetime.fromisoformat(transaction['timestamp'].replace('Z', '+00:00'))
                    formatted_time = dt.strftime('%m/%d %H:%M')
                except:
                    formatted_time = "Unknown"
                
                type_emoji = "➕" if transaction['type'] == 'deposit' else "➖"
                count = transaction['count']
                # Escape special Markdown characters in name
                name = escape_markdown(transaction['name'])
                
                status_message += f"{type_emoji} *{count}* pts - {name}\n"
                status_message += f"   ⏰ {formatted_time}\n"
        else:
            status_message += "\n📋 *Recent Activity:* No transactions found\n"
        
        # Add monitoring status
        global monitoring_task
        if BALANCE_MONITORING_ENABLED:
            monitoring_active = monitoring_task and not monitoring_task.done()
            status_emoji = "🟢" if monitoring_active else "🔴"
            status_text = "ACTIVE" if monitoring_active else "INACTIVE"
            status_message += f"\n🔔 *Monitoring:* {status_emoji} {status_text}\n"
            status_message += f"⚠️ *Low Balance Alert:* {LOW_BALANCE_THRESHOLD} points"
        else:
            status_message += "\n🔔 *Monitoring:* 🔴 DISABLED"
        
        await update.message.reply_text(status_message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        # Fallback to plain text if Markdown fails
        try:
            await update.message.reply_text(
                f"📊 Fitness Rewards Status 📊\n\n"
                f"💰 Current Balance: {balance_amount} points\n"
                f"❌ Error displaying detailed status. Use /balance and /transactions separately."
            )
        except:
            await update.message.reply_text(
                "❌ Failed to get status. Please try again later."
            )

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Withdraw points with activity selection."""
    try:
        if not context.args:
            await update.message.reply_text(
                "❌ Please specify the amount to withdraw.\n"
                "Example: `/withdraw 50`"
            )
            return
        
        try:
            amount = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "❌ Please provide a valid number.\n"
                "Example: `/withdraw 50`"
            )
            return
        
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0.")
            return
        
        # Create activity selection keyboard
        keyboard = [
            [InlineKeyboardButton("📺 Watching TV", callback_data=f"withdraw_tv_{amount}")],
            [InlineKeyboardButton("🎮 Gaming", callback_data=f"withdraw_gaming_{amount}")],
            [InlineKeyboardButton("🍿 Snack Break", callback_data=f"withdraw_snack_{amount}")],
            [InlineKeyboardButton("📱 Social Media", callback_data=f"withdraw_social_{amount}")],
            [InlineKeyboardButton("🎵 Music/Podcast", callback_data=f"withdraw_music_{amount}")],
            [InlineKeyboardButton("📖 Reading", callback_data=f"withdraw_reading_{amount}")],
            [InlineKeyboardButton("🎬 Movie Time", callback_data=f"withdraw_movie_{amount}")],
            [InlineKeyboardButton("☕ Coffee Break", callback_data=f"withdraw_coffee_{amount}")],
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"💳 **Withdrawing {amount} points**\n\n"
            "What activity are you doing?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in withdraw command: {e}")
        await update.message.reply_text(
            "❌ An error occurred. Please try again later."
        )

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deposit points with source selection."""
    try:
        if not context.args:
            await update.message.reply_text(
                "❌ Please specify the amount to deposit.\n"
                "Example: `/deposit 100`"
            )
            return
        
        try:
            amount = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "❌ Please provide a valid number.\n"
                "Example: `/deposit 100`"
            )
            return
        
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0.")
            return
        
        # Create source selection keyboard
        keyboard = [
            [InlineKeyboardButton("🏃‍♂️ Workout Complete", callback_data=f"deposit_workout_{amount}")],
            [InlineKeyboardButton("🚴‍♀️ Cardio Session", callback_data=f"deposit_cardio_{amount}")],
            [InlineKeyboardButton("🏋️‍♂️ Strength Training", callback_data=f"deposit_strength_{amount}")],
            [InlineKeyboardButton("🧘‍♀️ Yoga/Meditation", callback_data=f"deposit_yoga_{amount}")],
            [InlineKeyboardButton("🚶‍♂️ Daily Walk", callback_data=f"deposit_walk_{amount}")],
            [InlineKeyboardButton("💪 Manual Bonus", callback_data=f"deposit_bonus_{amount}")],
            [InlineKeyboardButton("🎯 Goal Achievement", callback_data=f"deposit_goal_{amount}")],
            [InlineKeyboardButton("🔄 Other Activity", callback_data=f"deposit_other_{amount}")],
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"💎 **Depositing {amount} points**\n\n"
            "What's the source of these points?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in deposit command: {e}")
        await update.message.reply_text(
            "❌ An error occurred. Please try again later."
        )

async def transactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get recent transactions."""
    try:
        limit = 10
        if context.args and context.args[0].isdigit():
            limit = min(int(context.args[0]), 20)  # Max 20 transactions
        
        result = await api.get_transactions(limit=limit)
        
        if not result:
            await update.message.reply_text("📝 No transactions found.")
            return
        
        message = f"📋 **Recent Transactions (Last {len(result)}):**\n\n"
        
        for transaction in result:
            # Format timestamp
            try:
                dt = datetime.fromisoformat(transaction['timestamp'].replace('Z', '+00:00'))
                formatted_time = dt.strftime('%m/%d %H:%M')
            except:
                formatted_time = transaction['timestamp']
            
            type_emoji = "➕" if transaction['type'] == 'deposit' else "➖"
            count = transaction['count']
            # Escape special Markdown characters in name
            name = escape_markdown(transaction['name'])
            balance_after = transaction['balance_after']
            
            message += f"{type_emoji} **{count}** pts - {name}\n"
            message += f"   ⏰ {formatted_time} | Balance: {balance_after}\n\n"
        
        # Split message if too long
        if len(message) > 4000:
            messages = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for i, msg in enumerate(messages):
                try:
                    await update.message.reply_text(msg, parse_mode='Markdown')
                except Exception as e:
                    logger.warning(f"Failed to send transactions message {i+1} with Markdown: {e}")
                    # Fallback without Markdown
                    fallback_msg = msg.replace('*', '').replace('_', '')
                    await update.message.reply_text(fallback_msg)
        else:
            try:
                await update.message.reply_text(message, parse_mode='Markdown')
            except Exception as e:
                logger.warning(f"Failed to send transactions with Markdown: {e}")
                # Fallback without Markdown
                fallback_message = message.replace('*', '').replace('_', '')
                await update.message.reply_text(fallback_message)
        
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        await update.message.reply_text(
            "❌ Failed to get transactions. Please try again later."
        )

async def monitor_balance_changes(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Monitor balance changes and send notifications for all changes."""
    global last_known_balance, low_balance_warning_sent
    
    logger.info("Starting balance monitoring...")
    
    # Initialize with current balance
    try:
        balance_data = await api.get_balance()
        last_known_balance = balance_data.get('balance', 0)
        logger.info(f"Initial balance: {last_known_balance}")
        
        # Check if we need to send a low balance warning on startup
        if last_known_balance <= LOW_BALANCE_THRESHOLD:
            await send_low_balance_notification(context, last_known_balance)
            low_balance_warning_sent = True
        else:
            low_balance_warning_sent = False
            
    except Exception as e:
        logger.error(f"Failed to get initial balance: {e}")
        return
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            await asyncio.sleep(BALANCE_CHECK_INTERVAL)
            
            # Get current balance
            balance_data = await api.get_balance()
            current_balance = balance_data.get('balance', 0)
            
            # Reset error counter on successful request
            consecutive_errors = 0
            
            # Check for low balance warning
            if current_balance <= LOW_BALANCE_THRESHOLD and not low_balance_warning_sent:
                await send_low_balance_notification(context, current_balance)
                low_balance_warning_sent = True
            elif current_balance > LOW_BALANCE_THRESHOLD and low_balance_warning_sent:
                # Reset low balance warning when balance goes above threshold
                low_balance_warning_sent = False
                logger.info(f"Balance recovered above threshold: {current_balance}")
            
            # Check if balance changed - send notification for ALL changes
            if last_known_balance is not None and current_balance != last_known_balance:
                logger.info(f"Balance changed from {last_known_balance} to {current_balance}")
                
                # Calculate change
                change = current_balance - last_known_balance
                action = "deposit" if change > 0 else "withdraw"
                amount = abs(change)
                
                # Get recent transactions for context
                try:
                    transactions = await api.get_transactions(limit=MAX_TRANSACTIONS_IN_NOTIFICATION)
                    
                    # Send notification for all balance changes with transaction details
                    await send_balance_change_notification(
                        context, action, amount, current_balance, transactions
                    )
                        
                except Exception as e:
                    logger.error(f"Error getting recent transactions: {e}")
                    # Send notification without transaction details
                    await send_balance_change_notification(
                        context, action, amount, current_balance, []
                    )
                
                # Update last known balance
                last_known_balance = current_balance
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Error in balance monitoring (attempt {consecutive_errors}): {e}")
            
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"Too many consecutive errors ({consecutive_errors}), stopping balance monitoring")
                break
            
            # Wait longer on error
            await asyncio.sleep(min(30, BALANCE_CHECK_INTERVAL * consecutive_errors))

async def send_low_balance_notification(context: ContextTypes.DEFAULT_TYPE, current_balance: int) -> None:
    """Send low balance warning to registered chats."""
    try:
        # Get registered chats
        chats = await api.get_registered_chats()
        
        if current_balance == 0:
            notification_text = (
                f"⚠️ **LOW BALANCE ALERT** ⚠️\n\n"
                f"💰 Your balance is **{current_balance}** points!\n"
                f"🚫 You're out of points!\n\n"
                f"💡 **Suggestions:**\n"
                f"• Complete a workout to earn points\n"
                f"• Use `/deposit` to add points manually\n"
                f"• Check `/transactions` to see recent activity\n\n"
                f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
            )
        else:
            notification_text = (
                f"⚠️ **LOW BALANCE ALERT** ⚠️\n\n"
                f"💰 Your balance is only **{current_balance}** points!\n"
                f"📉 Balance is below the {LOW_BALANCE_THRESHOLD} point threshold.\n\n"
                f"💡 **Suggestions:**\n"
                f"• Complete a workout to earn more points\n"
                f"• Use `/deposit` to add points manually\n"
                f"• Check `/transactions` to see recent activity\n\n"
                f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
            )
        
        for chat_info in chats:
            chat_id = chat_info['chat_id']
            
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=notification_text,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.warning(f"Failed to send low balance notification to chat {chat_id}: {e}")
                # Try fallback without Markdown
                try:
                    fallback_text = notification_text.replace('*', '').replace('_', '')
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=fallback_text
                    )
                except Exception as e2:
                    logger.error(f"Failed to send fallback low balance notification to chat {chat_id}: {e2}")
        
        logger.info(f"Low balance notification sent for balance: {current_balance}")
    
    except Exception as e:
        logger.error(f"Error sending low balance notifications: {e}")

async def send_balance_change_notification(context: ContextTypes.DEFAULT_TYPE, action: str,
                                         amount: int, new_balance: int, transactions: list = None) -> None:
    """Send notification for any balance change with recent transactions."""
    try:
        # Get registered chats
        chats = await api.get_registered_chats()
        
        if not chats:
            logger.info("No registered chats to send notifications to")
            return
        
        emoji = "💳" if action == 'withdraw' else "💎"
        action_text = "Withdrew" if action == 'withdraw' else "Deposited"
        
        # Build the main notification
        notification_text = (
            f"🔔 **Balance Update** 📊\n\n"
            f"{emoji} {action_text} **{amount}** points\n"
            f"💰 New Balance: **{new_balance}** points\n"
        )
        
        # Add transaction details if available
        if transactions and len(transactions) > 0:
            notification_text += "\n📋 **Recent Activity:**\n"
            
            for i, transaction in enumerate(transactions[:MAX_TRANSACTIONS_IN_NOTIFICATION]):
                # Format timestamp
                try:
                    dt = datetime.fromisoformat(transaction['timestamp'].replace('Z', '+00:00'))
                    formatted_time = dt.strftime('%H:%M:%S')
                except:
                    formatted_time = "Unknown"
                
                type_emoji = "➕" if transaction['type'] == 'deposit' else "➖"
                count = transaction['count']
                # Escape special Markdown characters in name
                name = escape_markdown(transaction['name'])
                
                notification_text += f"{type_emoji} **{count}** pts - {name}\n"
                notification_text += f"   ⏰ {formatted_time}\n"
                
                if i < min(len(transactions), MAX_TRANSACTIONS_IN_NOTIFICATION) - 1:
                    notification_text += "\n"
            
            if len(transactions) > MAX_TRANSACTIONS_IN_NOTIFICATION:
                notification_text += f"\n... and {len(transactions) - MAX_TRANSACTIONS_IN_NOTIFICATION} more"
        else:
            # No transactions available
            notification_text += "\n📋 **Recent Activity:** No details available"
        
        # Add timestamp
        notification_text += f"\n\n🕒 Updated: {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
        
        # Add low balance warning if applicable
        if new_balance <= LOW_BALANCE_THRESHOLD:
            notification_text += f"\n\n⚠️ **LOW BALANCE WARNING**\nOnly {new_balance} points remaining!"
        
        current_time = datetime.now(timezone.utc)
        
        for chat_info in chats:
            chat_id = chat_info['chat_id']
            
            try:
                # Send notification
                message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=notification_text,
                    parse_mode='Markdown'
                )
                
                # Store message info for potential future edits
                last_notification_messages[chat_id] = {
                    'message_id': message.message_id,
                    'timestamp': current_time
                }
                
            except Exception as e:
                logger.warning(f"Failed to send balance change notification to chat {chat_id}: {e}")
                # Try sending without Markdown formatting as fallback
                try:
                    fallback_text = notification_text.replace('*', '').replace('_', '')
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=fallback_text
                    )
                except Exception as e2:
                    logger.error(f"Failed to send fallback notification to chat {chat_id}: {e2}")
    
    except Exception as e:
        logger.error(f"Error sending balance change notifications: {e}")

async def start_balance_monitoring(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the balance monitoring task."""
    global monitoring_task
    
    if not BALANCE_MONITORING_ENABLED:
        logger.info("Balance monitoring is disabled via configuration")
        return
    
    if monitoring_task is None or monitoring_task.done():
        monitoring_task = asyncio.create_task(monitor_balance_changes(context))
        logger.info("Balance monitoring task started")
    else:
        logger.info("Balance monitoring task already running")

async def stop_balance_monitoring() -> None:
    """Stop the balance monitoring task."""
    global monitoring_task
    
    if monitoring_task and not monitoring_task.done():
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass
        logger.info("Balance monitoring task stopped")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands."""
    await update.message.reply_text(
        "❓ Unknown command. Type /help to see available commands."
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks from inline keyboards."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    
    callback_data = query.data
    
    try:
        if callback_data.startswith("withdraw_"):
            await handle_withdraw_callback(query, callback_data)
        elif callback_data.startswith("deposit_"):
            await handle_deposit_callback(query, callback_data)
        else:
            await query.edit_message_text("❌ Unknown action.")
            
    except Exception as e:
        logger.error(f"Error handling button callback: {e}")
        try:
            await query.edit_message_text(
                "❌ An error occurred while processing your request. Please try again."
            )
        except:
            # If editing fails, send a new message
            await query.message.reply_text(
                "❌ An error occurred while processing your request. Please try again."
            )

async def handle_withdraw_callback(query, callback_data: str) -> None:
    """Handle withdraw button callbacks."""
    try:
        # Parse callback data: withdraw_{activity}_{amount}
        parts = callback_data.split("_")
        if len(parts) < 3:
            await query.edit_message_text("❌ Invalid withdraw data.")
            return
            
        activity = parts[1]
        amount = int(parts[2])
        
        # Map activity codes to display names
        activity_names = {
            'tv': 'Watching TV 📺',
            'gaming': 'Gaming 🎮',
            'snack': 'Snack Break 🍿',
            'social': 'Social Media 📱',
            'music': 'Music/Podcast 🎵',
            'reading': 'Reading 📖',
            'movie': 'Movie Time 🎬',
            'coffee': 'Coffee Break ☕'
        }
        
        activity_name = activity_names.get(activity, activity.title())
        
        # Perform the withdrawal
        result = await api.withdraw_points(activity_name, amount)
        
        new_balance = result.get('balance', 'Unknown')
        message = (
            f"✅ **Withdrawal Successful!**\n\n"
            f"💳 Withdrew **{amount}** points\n"
            f"🎯 Activity: {activity_name}\n"
            f"💰 New Balance: **{new_balance}** points\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
        )
        
        await query.edit_message_text(message, parse_mode='Markdown')
        
    except ValueError:
        await query.edit_message_text("❌ Invalid amount in withdraw data.")
    except Exception as e:
        logger.error(f"Error in withdraw callback: {e}")
        if "insufficient" in str(e).lower() or "balance" in str(e).lower():
            await query.edit_message_text(
                f"❌ Insufficient balance to withdraw {amount} points.\n"
                "Check your current balance with /balance"
            )
        else:
            await query.edit_message_text(
                f"❌ Failed to withdraw points: {str(e)}"
            )

async def handle_deposit_callback(query, callback_data: str) -> None:
    """Handle deposit button callbacks."""
    try:
        # Parse callback data: deposit_{activity}_{amount}
        parts = callback_data.split("_")
        if len(parts) < 3:
            await query.edit_message_text("❌ Invalid deposit data.")
            return
            
        activity = parts[1]
        amount = int(parts[2])
        
        # Map activity codes to display names
        activity_names = {
            'workout': 'Workout Complete 🏃‍♂️',
            'cardio': 'Cardio Session 🚴‍♀️',
            'strength': 'Strength Training 🏋️‍♂️',
            'yoga': 'Yoga/Meditation 🧘‍♀️',
            'walk': 'Daily Walk 🚶‍♂️',
            'bonus': 'Manual Bonus 💪',
            'goal': 'Goal Achievement 🎯',
            'other': 'Other Activity 🔄'
        }
        
        activity_name = activity_names.get(activity, activity.title())
        
        # Perform the deposit
        result = await api.deposit_points(activity_name, amount)
        
        new_balance = result.get('balance', 'Unknown')
        message = (
            f"✅ **Deposit Successful!**\n\n"
            f"💎 Deposited **{amount}** points\n"
            f"🎯 Source: {activity_name}\n"
            f"💰 New Balance: **{new_balance}** points\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
        )
        
        await query.edit_message_text(message, parse_mode='Markdown')
        
    except ValueError:
        await query.edit_message_text("❌ Invalid amount in deposit data.")
    except Exception as e:
        logger.error(f"Error in deposit callback: {e}")
        await query.edit_message_text(
            f"❌ Failed to deposit points: {str(e)}"
        )

async def post_init(application: Application) -> None:
    """Called after the application is initialized."""
    # Set up bot commands for autocomplete
    commands = [
        BotCommand("start", "Welcome message and instructions"),
        BotCommand("balance", "Check your current point balance"),
        BotCommand("status", "Get detailed balance and activity status"),
        BotCommand("withdraw", "Withdraw points (usage: /withdraw {amount})"),
        BotCommand("deposit", "Add points manually (usage: /deposit {amount})"),
        BotCommand("transactions", "View recent transaction history"),
        BotCommand("register", "Register for balance change notifications"),
        BotCommand("unregister", "Unregister from balance change notifications"),
        BotCommand("monitoring", "Check balance monitoring status"),
        BotCommand("help", "Show help message"),
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully for autocomplete")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")
    
    # Create a fake context for the monitoring task
    from telegram.ext import ContextTypes
    
    # Start balance monitoring with a minimal context
    # In newer versions, we create context with just the application
    context = ContextTypes.DEFAULT_TYPE(application=application)
    await start_balance_monitoring(context)

async def post_shutdown(application: Application) -> None:
    """Called before the application shuts down."""
    # Stop balance monitoring
    await stop_balance_monitoring()

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("unregister", unregister))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("withdraw", withdraw))
    application.add_handler(CommandHandler("deposit", deposit))
    application.add_handler(CommandHandler("transactions", transactions))
    
    # Add callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add handler for unknown commands
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # Add post init and shutdown handlers
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    logger.info("Starting Fitness Rewards Telegram Bot...")
    logger.info(f"Server URL: {SERVER_URL}")
    logger.info(f"Balance monitoring: {'enabled' if BALANCE_MONITORING_ENABLED else 'disabled'}")
    if BALANCE_MONITORING_ENABLED:
        logger.info(f"Balance check interval: {BALANCE_CHECK_INTERVAL} seconds")
        logger.info(f"Low balance threshold: {LOW_BALANCE_THRESHOLD} points")
        logger.info(f"Max transactions in notifications: {MAX_TRANSACTIONS_IN_NOTIFICATION}")
    
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Telegram Bot for Fitness Rewards System

This bot provides an interface to interact with the fitness rewards server
through Telegram commands.

Commands:
- /start - Welcome message and instructions
- /register - Register chat for notifications
- /balance - Get current point balance
- /withdraw {amount} - Withdraw points for an activity
- /deposit {amount} - Deposit points manually
- /transactions - Get recent transactions
- /help - Show help message
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
NOTIFICATION_EDIT_WINDOW = int(os.getenv("NOTIFICATION_EDIT_WINDOW", "5"))  # minutes
BALANCE_MONITORING_ENABLED = os.getenv("BALANCE_MONITORING_ENABLED", "true").lower() == "true"
BALANCE_CHECK_INTERVAL = int(os.getenv("BALANCE_CHECK_INTERVAL", "5"))  # seconds

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

# Global variables for notification management
last_notification_messages: Dict[int, Dict[str, Any]] = {}
last_known_balance: Optional[int] = None
monitoring_task: Optional[asyncio.Task] = None

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

# Initialize API client
api = FitnessRewardsAPI(SERVER_URL, API_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    welcome_text = """
🏃‍♂️ **Welcome to Fitness Rewards Bot!** 🏃‍♀️

This bot helps you manage your fitness reward points. Here are the available commands:

🔹 `/balance` - Check your current point balance
🔹 `/withdraw {amount}` - Withdraw points for activities (e.g., `/withdraw 50`)
🔹 `/deposit {amount}` - Add points manually (e.g., `/deposit 100`)
🔹 `/transactions` - View recent transaction history
🔹 `/register` - Register for balance change notifications
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
            name = transaction['name']
            balance_after = transaction['balance_after']
            
            message += f"{type_emoji} **{count}** pts - {name}\n"
            message += f"   ⏰ {formatted_time} | Balance: {balance_after}\n\n"
        
        # Split message if too long
        if len(message) > 4000:
            messages = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for msg in messages:
                await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        await update.message.reply_text(
            "❌ Failed to get transactions. Please try again later."
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    try:
        data = query.data
        
        if data == "restart_monitoring":
            # Restart monitoring
            await stop_balance_monitoring()
            await start_balance_monitoring(context)
            await query.edit_message_text(
                "🔄 **Monitoring Restarted**\n\n"
                f"Balance monitoring has been restarted.\n"
                f"Check interval: {BALANCE_CHECK_INTERVAL} seconds",
                parse_mode='Markdown'
            )
            return
        
        parts = data.split('_')
        
        if len(parts) < 3:
            await query.edit_message_text("❌ Invalid action.")
            return
        
        action = parts[0]  # 'withdraw' or 'deposit'
        activity = parts[1]  # activity/source name
        amount = int(parts[2])
        
        # Map activity codes to readable names
        activity_names = {
            'tv': 'watching TV',
            'gaming': 'gaming',
            'snack': 'snack break',
            'social': 'social media',
            'music': 'music/podcast',
            'reading': 'reading',
            'movie': 'movie time',
            'coffee': 'coffee break',
            'workout': 'workout session',
            'cardio': 'cardio session',
            'strength': 'strength training',
            'yoga': 'yoga/meditation',
            'walk': 'daily walk',
            'bonus': 'manual bonus',
            'goal': 'goal achievement',
            'other': 'other activity'
        }
        
        activity_name = activity_names.get(activity, activity)
        
        if action == 'withdraw':
            result = await api.withdraw_points(activity_name, amount)
            emoji = "💳"
            action_text = "Withdrew"
        else:  # deposit
            result = await api.deposit_points(activity_name, amount)
            emoji = "💎"
            action_text = "Deposited"
        
        balance_key = 'balance_remaining' if action == 'withdraw' else 'balance_total'
        new_balance = result.get(balance_key, 0)
        
        success_message = (
            f"{emoji} **{action_text} {amount} points**\n\n"
            f"🎯 **Activity:** {activity_name.title()}\n"
            f"💰 **New Balance:** {new_balance} points\n"
            f"✅ **Status:** Success"
        )
        
        await query.edit_message_text(success_message, parse_mode='Markdown')
        
        # Send notification to registered chats
        await send_balance_notification(
            context, 
            action, 
            amount, 
            activity_name, 
            new_balance,
            exclude_chat_id=query.message.chat_id
        )
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            error_detail = e.response.json().get('detail', 'Bad request')
            await query.edit_message_text(f"❌ {error_detail}")
        else:
            await query.edit_message_text("❌ Server error. Please try again later.")
    except Exception as e:
        logger.error(f"Error in button callback: {e}")
        await query.edit_message_text("❌ An error occurred. Please try again later.")

async def send_balance_notification(context: ContextTypes.DEFAULT_TYPE, action: str, 
                                  amount: int, activity: str, new_balance: int, 
                                  exclude_chat_id: int = None) -> None:
    """Send balance change notifications to registered chats."""
    try:
        # Get registered chats from the API
        chats = await api.get_registered_chats()
        
        emoji = "💳" if action == 'withdraw' else "💎"
        action_text = "Withdrew" if action == 'withdraw' else "Deposited"
        
        notification_text = (
            f"🔔 **Balance Update**\n\n"
            f"{emoji} {action_text} **{amount}** points\n"
            f"🎯 Activity: {activity.title()}\n"
            f"💰 New Balance: **{new_balance}** points"
        )
        
        current_time = datetime.now(timezone.utc)
        
        for chat_info in chats:
            chat_id = chat_info['chat_id']
            
            # Skip the chat that initiated the action
            if exclude_chat_id and chat_id == exclude_chat_id:
                continue
            
            try:
                # Check if we should edit an existing message or send a new one
                should_edit = False
                if chat_id in last_notification_messages:
                    last_msg_info = last_notification_messages[chat_id]
                    time_diff = current_time - last_msg_info['timestamp']
                    
                    if time_diff.total_seconds() < (NOTIFICATION_EDIT_WINDOW * 60):
                        should_edit = True
                
                if should_edit:
                    # Edit the existing message
                    msg_info = last_notification_messages[chat_id]
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=msg_info['message_id'],
                            text=notification_text,
                            parse_mode='Markdown'
                        )
                        # Update timestamp
                        last_notification_messages[chat_id]['timestamp'] = current_time
                    except Exception as edit_error:
                        logger.warning(f"Failed to edit message for chat {chat_id}: {edit_error}")
                        # If edit fails, send a new message
                        should_edit = False
                
                if not should_edit:
                    # Send a new message
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
                logger.warning(f"Failed to send notification to chat {chat_id}: {e}")
                # Remove chat from tracking if it's not accessible
                if chat_id in last_notification_messages:
                    del last_notification_messages[chat_id]
    
    except Exception as e:
        logger.error(f"Error sending notifications: {e}")

async def monitor_balance_changes(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Monitor balance changes from external sources and send notifications."""
    global last_known_balance
    
    logger.info("Starting balance monitoring...")
    
    # Initialize with current balance
    try:
        balance_data = await api.get_balance()
        last_known_balance = balance_data.get('balance', 0)
        logger.info(f"Initial balance: {last_known_balance}")
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
            
            # Check if balance changed
            if last_known_balance is not None and current_balance != last_known_balance:
                logger.info(f"Balance changed from {last_known_balance} to {current_balance}")
                
                # Calculate change
                change = current_balance - last_known_balance
                action = "deposit" if change > 0 else "withdraw"
                amount = abs(change)
                
                # Get the most recent transaction to determine activity
                try:
                    transactions = await api.get_transactions(limit=1)
                    if transactions:
                        latest_transaction = transactions[0]
                        activity = latest_transaction.get('name', 'external activity')
                        
                        # Check if this transaction is from the last few seconds (likely external)
                        transaction_time = datetime.fromisoformat(
                            latest_transaction['timestamp'].replace('Z', '+00:00')
                        )
                        time_diff = datetime.now(timezone.utc) - transaction_time
                        
                        # If transaction is recent (within check interval + 5 seconds), it's likely external
                        if time_diff.total_seconds() <= (BALANCE_CHECK_INTERVAL + 5):
                            # Send notification for external change
                            await send_external_balance_notification(
                                context, action, amount, activity, current_balance
                            )
                        else:
                            # Old transaction, might be from our own bot action
                            logger.info("Balance change detected but transaction is old, skipping notification")
                    else:
                        # No transactions found, send generic notification
                        await send_external_balance_notification(
                            context, action, amount, "external activity", current_balance
                        )
                        
                except Exception as e:
                    logger.error(f"Error getting recent transactions: {e}")
                    # Send generic notification anyway
                    await send_external_balance_notification(
                        context, action, amount, "external activity", current_balance
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

async def send_external_balance_notification(context: ContextTypes.DEFAULT_TYPE, action: str,
                                           amount: int, activity: str, new_balance: int) -> None:
    """Send notification for external balance changes."""
    try:
        # Get registered chats
        chats = await api.get_registered_chats()
        
        emoji = "💳" if action == 'withdraw' else "💎"
        action_text = "Withdrew" if action == 'withdraw' else "Deposited"
        source_emoji = "🤖" if "hardware" in activity.lower() or "tracker" in activity.lower() else "🌐"
        
        notification_text = (
            f"🔔 **External Balance Update** {source_emoji}\n\n"
            f"{emoji} {action_text} **{amount}** points\n"
            f"🎯 Source: {activity.title()}\n"
            f"💰 New Balance: **{new_balance}** points\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
        )
        
        current_time = datetime.now(timezone.utc)
        
        for chat_info in chats:
            chat_id = chat_info['chat_id']
            
            try:
                # Always send new message for external notifications
                # (don't edit previous messages as these are important updates)
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
                logger.warning(f"Failed to send external notification to chat {chat_id}: {e}")
    
    except Exception as e:
        logger.error(f"Error sending external notifications: {e}")

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

async def monitoring_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check the status of balance monitoring."""
    global monitoring_task, last_known_balance
    
    if not BALANCE_MONITORING_ENABLED:
        await update.message.reply_text(
            "🔴 **Monitoring Status: DISABLED**\n\n"
            "Balance monitoring is disabled via configuration.",
            parse_mode='Markdown'
        )
        return
    
    status_emoji = "🟢" if monitoring_task and not monitoring_task.done() else "🔴"
    status_text = "RUNNING" if monitoring_task and not monitoring_task.done() else "STOPPED"
    
    message = f"{status_emoji} **Monitoring Status: {status_text}**\n\n"
    message += f"🔧 **Check Interval:** {BALANCE_CHECK_INTERVAL} seconds\n"
    
    if last_known_balance is not None:
        message += f"💰 **Last Known Balance:** {last_known_balance} points\n"
    
    # Add restart button if monitoring is stopped
    if not monitoring_task or monitoring_task.done():
        keyboard = [[InlineKeyboardButton("🔄 Restart Monitoring", callback_data="restart_monitoring")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, parse_mode='Markdown')

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands."""
    await update.message.reply_text(
        "❓ Unknown command. Type /help to see available commands."
    )

async def post_init(application: Application) -> None:
    """Called after the application is initialized."""
    # Set up bot commands for autocomplete
    commands = [
        BotCommand("start", "Welcome message and instructions"),
        BotCommand("balance", "Check your current point balance"),
        BotCommand("withdraw", "Withdraw points (usage: /withdraw {amount})"),
        BotCommand("deposit", "Add points manually (usage: /deposit {amount})"),
        BotCommand("transactions", "View recent transaction history"),
        BotCommand("register", "Register for balance change notifications"),
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
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("withdraw", withdraw))
    application.add_handler(CommandHandler("deposit", deposit))
    application.add_handler(CommandHandler("transactions", transactions))
    application.add_handler(CommandHandler("monitoring", monitoring_status))
    
    # Add callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add handler for unknown commands
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # Add post init and shutdown handlers
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    logger.info("Starting Fitness Rewards Telegram Bot...")
    logger.info(f"Server URL: {SERVER_URL}")
    logger.info(f"Notification edit window: {NOTIFICATION_EDIT_WINDOW} minutes")
    logger.info(f"Balance monitoring: {'enabled' if BALANCE_MONITORING_ENABLED else 'disabled'}")
    if BALANCE_MONITORING_ENABLED:
        logger.info(f"Balance check interval: {BALANCE_CHECK_INTERVAL} seconds")
    
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

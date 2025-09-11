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
from typing import Optional, Dict, Any, List
from collections import defaultdict
from telegram import Update, BotCommand
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "your-secret-api-key-123")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

# GMT+3 timezone
GMT_PLUS_3 = timezone(timedelta(hours=3))

def format_datetime_for_user(dt_str: str, format_type: str = 'full') -> str:
    """
    Format datetime string for user display in GMT+3 timezone.
    
    Args:
        dt_str: ISO format datetime string or timestamp
        format_type: 'full' for full datetime, 'short' for MM/DD HH:MM, 'time' for HH:MM:SS
    
    Returns:
        Formatted datetime string in GMT+3
    """
    try:
        # Parse ISO format datetime (handle both with and without 'Z')
        if dt_str.endswith('Z'):
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(dt_str)
        
        # Convert to GMT+3
        dt_gmt3 = dt.astimezone(GMT_PLUS_3)
        
        # Format based on type
        if format_type == 'full':
            return dt_gmt3.strftime('%Y-%m-%d %H:%M:%S GMT+3')
        elif format_type == 'short':
            return dt_gmt3.strftime('%m/%d %H:%M')
        elif format_type == 'time':
            return dt_gmt3.strftime('%H:%M:%S')
        else:
            return dt_gmt3.strftime('%Y-%m-%d %H:%M:%S GMT+3')
    except:
        return dt_str if dt_str else "Unknown"

def get_current_time_gmt3(format_type: str = 'time') -> str:
    """Get current time formatted in GMT+3."""
    now = datetime.now(GMT_PLUS_3)
    if format_type == 'time':
        return now.strftime('%H:%M:%S')
    elif format_type == 'full':
        return now.strftime('%Y-%m-%d %H:%M:%S GMT+3')
    else:
        return now.strftime('%H:%M:%S')

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
    
    async def get_transactions(
        self, 
        limit: int = 10, 
        transaction_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> list:
        """Get recent transactions with optional date filtering."""
        async with httpx.AsyncClient() as client:
            params = {"limit": limit}
            if transaction_type:
                params["type"] = transaction_type
            if start_date:
                params["start_date"] = start_date.isoformat()
            if end_date:
                params["end_date"] = end_date.isoformat()
            
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
**Fitness Rewards Bot'a Hoşgeldiniz!**

Bu bot fitness ödül puanlarınızı yönetmenize yardımcı olur. Kullanılabilir komutlar:

/balance - Mevcut puan bakiyenizi kontrol edin
/status - Detaylı bakiye ve aktivite durumu
/withdraw {miktar} [isim] - Puan çekin (örn. /withdraw 50 veya /withdraw 50 TV İzleme)
/deposit {miktar} [isim] - Puan ekleyin (örn. /deposit 100 veya /deposit 100 Egzersiz)
/transactions - Son işlem geçmişini görüntüleyin
/register - Bakiye değişikliği bildirimlerine kaydolun
/unregister - Bakiye değişikliği bildirimlerinden çıkın
/help - Bu yardım mesajını göster

**Örnekler:**
/withdraw 30 - "Genel Aktivite" için 30 puan çek
/withdraw 30 TV İzleme - "TV İzleme" için 30 puan çek
/deposit 50 - "Manuel Yatırım" olarak 50 puan ekle
/deposit 50 Kardiyyo Seansı - "Kardiyyo Seansı" için 50 puan ekle
/transactions - Son 10 işleminizi görün

Başlamak için mevcut puanlarınızı görmek için /balance yazın!
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
            "Artık bakiyeniz değiştiğinde bildirim alacaksınız!"
            "Bildirimleri devre dışı bırakmak için istediğiniz zaman /unregister kullanabilirsiniz."
        )
        
    except Exception as e:
        logger.error(f"Error registering chat: {e}")
        await update.message.reply_text(
            "❌ Bildirimlere kaydolunamadı. Lütfen daha sonra tekrar deneyin."
        )

async def unregister(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unregister the chat from notifications."""
    try:
        chat_id = update.effective_chat.id
        
        result = await api.unregister_chat(chat_id=chat_id)
        
        await update.message.reply_text(
                "Artık bakiyeniz değiştiğinde bildirim almayacaksınız.\n"
                "Bildirimleri yeniden etkinleştirmek için istediğiniz zaman /register kullanabilirsiniz."
        )
        
        
    except Exception as e:
        logger.error(f"Error unregistering chat: {e}")
        await update.message.reply_text(
            "❌ Bildirim kaydı kaldırılamadı. Lütfen daha sonra tekrar deneyin."
        )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get current balance."""
    try:
        result = await api.get_balance()
        balance_amount = result.get('balance', 0)
        last_updated = result.get('last_updated', 'Unknown')
        
        # Parse and format the timestamp
        formatted_time = format_datetime_for_user(last_updated, 'full')

        message = f"💰 **Bakiye:** {balance_amount} puan\n📅 **Son Güncelleme:** {formatted_time}"
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
        await update.message.reply_text(
            "❌ Bakiye alınamadı. Lütfen daha sonra tekrar deneyin."
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get detailed status including balance and today's transaction summary."""
    try:
        # Get balance
        balance_result = await api.get_balance()
        balance_amount = balance_result.get('balance', 0)
        last_updated = balance_result.get('last_updated', 'Unknown')
        
        # Format timestamp
        formatted_time = format_datetime_for_user(last_updated, 'full')
        
        # Get today's date range in GMT+3
        now_gmt3 = datetime.now(GMT_PLUS_3)
        today_start = now_gmt3.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now_gmt3.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Get today's transactions
        today_transactions = await api.get_transactions(
            limit=100,  # Get enough to cover a full day
            start_date=today_start,
            end_date=today_end
        )
        
        # Build status message (escape special characters for Markdown)
        status_message = "📊 *Fitnes Ödül Durumu* 📊\n\n"
        status_message += f"💰 *Bakiye:* {balance_amount} puan\n"
        status_message += f"📅 *Son Güncelleme:* {formatted_time}\n"

        # Add today's summary
        today_formatted = now_gmt3.strftime('%Y-%m-%d')
        status_message += f"\n *Bugün Özeti ({today_formatted}):*\n"
        
        if today_transactions:
            # Group transactions by name and type, sum counts
            summary = defaultdict(lambda: {'deposit': 0, 'withdraw': 0})
            
            for transaction in today_transactions:
                name = transaction['name']
                trans_type = transaction['type']
                count = transaction['count']
                summary[name][trans_type] += count
            
            # Calculate totals
            total_deposits = sum(item['deposit'] for item in summary.values())
            total_withdrawals = sum(item['withdraw'] for item in summary.values())
            net_change = total_deposits - total_withdrawals
            
            # Display summary by activity
            for name, amounts in summary.items():
                deposits = amounts['deposit']
                withdrawals = amounts['withdraw']
                escaped_name = escape_markdown(name)
                
                if deposits > 0 and withdrawals > 0:
                    net = deposits - withdrawals
                    net_emoji = "➕" if net > 0 else "➖"
                    status_message += f"🔄 *{escaped_name}:* ➕{deposits} ➖{withdrawals} ({net_emoji}{abs(net)})\n"
                elif deposits > 0:
                    status_message += f"➕ *{escaped_name}:* +{deposits} puan\n"
                elif withdrawals > 0:
                    status_message += f"➖ *{escaped_name}:* -{withdrawals} puan\n"
            
            # Add totals
            status_message += f"\n📊 *Günlük Toplamlar:*\n"
            status_message += f"➕ *Toplam Kazanılan:* {total_deposits} puan\n"
            status_message += f"➖ *Toplam Harcanan:* {total_withdrawals} puan\n"

            net_emoji = "🟢" if net_change > 0 else "🔴" if net_change < 0 else "⚪"
            sign = "+" if net_change > 0 else ""
            status_message += f"{net_emoji} *Net Değişim:* {sign}{net_change} puan\n"

        else:
            status_message += "Bugün için henüz işlem yok.\n"

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
    """Withdraw points with optional activity name."""
    try:
        if not context.args:
            await update.message.reply_text(
                "❌ Lütfen çekilecek miktarı belirtin.\n"
                "Kullanım: `/withdraw {miktar}` veya `/withdraw {miktar} {aktivite}`\n"
                "Örnek: `/withdraw 50` veya `/withdraw 50 TV İzleme`"
            )
            return
        
        try:
            amount = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "❌ Lütfen geçerli bir sayı girin.\n"
                "Kullanım: `/withdraw {miktar}` veya `/withdraw {miktar} {aktivite}`\n"
                "Örnek: `/withdraw 50` veya `/withdraw 50 Oyun`"
            )
            return
        
        if amount <= 0:
            await update.message.reply_text("❌ Miktar 0'dan büyük olmalıdır.")
            return
        
        # Get activity name from remaining arguments or use default
        if len(context.args) > 1:
            activity_name = " ".join(context.args[1:])
        else:
            activity_name = "Manuel"
        
        # Perform the withdrawal
        result = await api.withdraw_points(activity_name, amount)
        
        new_balance = result.get('balance', 'Unknown')
        message = (
            f"✅ **Çekme işlemi başarılı!**\n\n"
            f"➖ **{amount}** puan çekildi\n"
            f"🏷️ Aktivite: {escape_markdown(activity_name)}\n"
            f"💰 Yeni Bakiye: **{new_balance}** puan\n"
            f"⏰ {get_current_time_gmt3('time')} GMT+3"
        )
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in withdraw command: {e}")
        if "insufficient" in str(e).lower() or "balance" in str(e).lower():
            await update.message.reply_text(
                f"❌ {amount} puan çekmek için yeterli bakiyeniz yok.\n"
                "Mevcut bakiyenizi /balance ile kontrol edebilirsiniz."
            )
        else:
            await update.message.reply_text(
                f"❌ Puan çekme işlemi başarısız oldu: {str(e)}"
            )
            
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Puan ekleme işlemi (isteğe bağlı kaynak adı ile)."""
    try:
        if not context.args:
            await update.message.reply_text(
                "❌ Lütfen eklenecek miktarı belirtin.\n"
                "Kullanım: `/deposit {miktar}` veya `/deposit {miktar} {kaynak_adı}`\n"
                "Örnek: `/deposit 100` veya `/deposit 100 Egzersiz Tamamlandı`"
            )
            return
        
        try:
            amount = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "❌ Lütfen geçerli bir sayı girin.\n"
                "Kullanım: `/deposit {miktar}` veya `/deposit {miktar} {kaynak_adı}`\n"
                "Örnek: `/deposit 100` veya `/deposit 100 Kardiyo Seansı`"
            )
            return
        
        if amount <= 0:
            await update.message.reply_text("❌ Miktar 0'dan büyük olmalıdır.")
            return
        
        # Kaynak adını kalan argümanlardan al veya varsayılanı kullan
        if len(context.args) > 1:
            source_name = " ".join(context.args[1:])
        else:
            source_name = "Manuel"
        
        # Puan ekleme işlemini gerçekleştir
        result = await api.deposit_points(source_name, amount)
        
        new_balance = result.get('balance', 'Unknown')
        message = (
            f"✅ **Yatırma işlemi başarılı!**\n\n"
            f"➕ **{amount}** puan eklendi\n"
            f"🏷️ Kaynak: {escape_markdown(source_name)}\n"
            f"💰 Yeni Bakiye: **{new_balance}** puan\n"
            f"⏰ {get_current_time_gmt3('time')} GMT+3"
        )
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in deposit command: {e}")
        await update.message.reply_text(
            f"❌ Puan ekleme işlemi başarısız oldu: {str(e)}"
        )

async def transactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Son işlemleri getirir."""
    try:
        limit = 10
        if context.args and context.args[0].isdigit():
            limit = min(int(context.args[0]), 20)  # Maksimum 20 işlem
        
        result = await api.get_transactions(limit=limit)
        
        if not result:
            await update.message.reply_text("📝 Hiç işlem bulunamadı.")
            return
        
        message = f"📋 **Son İşlemler (Son {len(result)}):**\n\n"
        
        for transaction in result:
            # Zaman damgasını biçimlendir
            formatted_time = format_datetime_for_user(transaction['timestamp'], 'short')
            
            type_emoji = "➕" if transaction['type'] == 'deposit' else "➖"
            count = transaction['count']
            # Ad içindeki özel Markdown karakterlerini kaçır
            name = escape_markdown(transaction['name'])
            balance_after = transaction['balance_after']
            
            message += f"{type_emoji} **{count}** puan - {name}\n"
            message += f"   ⏰ {formatted_time} | Bakiye: {balance_after}\n\n"
        
        # Mesaj çok uzunsa böl
        if len(message) > 4000:
            messages = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for i, msg in enumerate(messages):
                try:
                    await update.message.reply_text(msg, parse_mode='Markdown')
                except Exception as e:
                    logger.warning(f"İşlem mesajı {i+1} Markdown ile gönderilemedi: {e}")
                    # Markdown olmadan gönder
                    fallback_msg = msg.replace('*', '').replace('_', '')
                    await update.message.reply_text(fallback_msg)
        else:
            try:
                await update.message.reply_text(message, parse_mode='Markdown')
            except Exception as e:
                logger.warning(f"İşlemler Markdown ile gönderilemedi: {e}")
                # Markdown olmadan gönder
                fallback_message = message.replace('*', '').replace('_', '')
                await update.message.reply_text(fallback_message)
        
    except Exception as e:
        logger.error(f"İşlemler alınırken hata: {e}")
        await update.message.reply_text(
            "❌ İşlemler alınamadı. Lütfen daha sonra tekrar deneyin."
        )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bilinmeyen komutları karşılar."""
    await update.message.reply_text(
        "❓ Bilinmeyen komut. Mevcut komutları görmek için /help yazın."
    )

async def post_init(application: Application) -> None:
    """Uygulama başlatıldıktan sonra çağrılır."""
    # Otomatik tamamlama için bot komutlarını ayarla
    commands = [
        BotCommand("start", "Karşılama mesajı ve talimatlar"),
        BotCommand("balance", "Mevcut puan bakiyenizi kontrol edin"),
        BotCommand("status", "Detaylı bakiye ve aktivite durumu"),
        BotCommand("withdraw", "Puan çek (kullanım: /withdraw {miktar})"),
        BotCommand("deposit", "Manuel puan ekle (kullanım: /deposit {miktar})"),
        BotCommand("transactions", "Son işlem geçmişini görüntüle"),
        BotCommand("register", "Bakiye değişikliği bildirimlerine kaydol"),
        BotCommand("unregister", "Bakiye değişikliği bildirimlerinden çık"),
        BotCommand("help", "Yardım mesajını göster"),
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot komutları otomatik tamamlama için başarıyla ayarlandı")
    except Exception as e:
        logger.error(f"Bot komutları ayarlanamadı: {e}")
            
    


async def post_shutdown(application: Application) -> None:
    """Called before the application shuts down."""
   

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
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
    
    # Add handler for unknown commands
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # Add post init and shutdown handlers
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    logger.info("Starting Fitness Rewards Telegram Bot...")
    logger.info(f"Server URL: {SERVER_URL}")

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

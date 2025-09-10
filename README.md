# 🏋️ Fitness Rewards System

A smart fitness tracking system that rewards your workouts with points! Connect ESP32 devices to track activities and manage rewards through a Telegram bot interface.

## ✨ Key Features

- 📊 **Workout Tracking** - Automatically log fitness events from ESP32 devices
- 🎯 **Point-Based Rewards** - Earn and spend points for various activities  
- 📱 **Telegram Bot** - Easy interaction through chat commands
- 📈 **Analytics** - Track progress with detailed workout history
- 🔐 **Secure API** - Protected endpoints with authentication

## 🤖 Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Get started with setup instructions |
| `/register` | Enable balance notifications |
| `/balance` | Check current points |
| `/withdraw 50` | Spend points on activities |
| `/deposit 100` | Add points manually |
| `/transactions` | View transaction history |

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- [uv](https://github.com/astral-sh/uv) package manager
- ESP32 device (optional)

### 1️⃣ Setup
```bash
git clone https://github.com/your-username/fitness-rewards.git
cd fitness-rewards
uv sync --extra test --extra dev
cp .env.example .env
```

### 2️⃣ Configure Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot`
2. Add your bot token to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   API_KEY=your_secure_key
   ```

### 3️⃣ Run with Docker (Recommended)
```bash
docker-compose up -d
```

### 3️⃣ Alternative: Local Development
```bash
# Terminal 1: Start API server
uv run python server.py

# Terminal 2: Start Telegram bot  
uv run python telegram_bot.py
```

📍 **API Documentation**: http://localhost:8000/docs

## 📁 Project Structure

```
├── server.py              # FastAPI application & business logic
├── telegram_bot.py        # Telegram bot interface  
├── main.ino              # ESP32 Arduino sketch
├── test_server.py        # API test suite
├── docker-compose.yml    # Container orchestration
└── pyproject.toml        # Dependencies & config
```

## 🔌 API Endpoints

> All endpoints require `x-api-key` header

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/webhook` | POST | Log fitness events from devices |
| `/balance` | GET | Get current point balance |
| `/withdraw` | GET | Spend points |
| `/deposit` | GET | Add points manually |
| `/workouts` | GET | Retrieve workout history |
| `/transactions` | GET | View transaction history |

## 🗄️ Database Schema

**SQLite** with 4 tables:
- `workout_events` - Device fitness events
- `balance` - Current point balance  
- `transactions` - Deposit/withdrawal history
- `chat_registrations` - Telegram chat IDs

## 🧪 Development

```bash
# Code quality
uv run black . && uv run isort . && uv run flake8 .

# Run tests
uv run pytest -v

# Specific test categories  
uv run pytest test_server.py::TestAuthentication
```

## 📝 License

This project is open source. Feel free to contribute!

"""Configuration settings for the Fitness Rewards API."""

import os

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fitness_rewards.db")
API_KEY = os.getenv("API_KEY", "your-secret-api-key-123")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

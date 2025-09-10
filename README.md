# Fitness Rewards API

A FastAPI application that receives and analyzes workout data from ESP32 devices, managing a point-based balance system for various fitness activities.

## Features

- **Fitness Event Tracking**: Log events from various fitness equipment (e.g., started, paused, resumed, stopped, revolution_add).
- **Flexible Point System**: Earn points from any tracked fitness activity.
- **Comprehensive Transaction History**: Keep a complete record of all point deposits and withdrawals.
- **Data Analytics**: Filter and retrieve workout data by date and device.
- **Secure API**: Protect endpoints with API key authentication.

## Getting Started

Follow these steps to get the project up and running on your local machine.

### Prerequisites

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) (for dependency management)
- An ESP32 device for hardware integration (optional)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/fitness-rewards.git
   cd fitness-rewards
   ```

2. **Install dependencies:**
   This project uses `uv` to manage dependencies.
   ```bash
   # Install main dependencies
   uv sync

   # Install test and development dependencies
   uv sync --extra test --extra dev
   ```

### Running the Server

To start the FastAPI server, run:
```bash
uv run python server.py
```
The API will be accessible at `http://localhost:8000`, with interactive documentation available at `http://localhost:8000/docs`.

## Project Structure

Here's an overview of the key files in this project:

- **`server.py`**: The main FastAPI application file. It defines API endpoints, handles business logic, and interacts with the database.
- **`test_server.py`**: Contains all the tests for the API, ensuring reliability and correctness.
- **`main.ino`**: An Arduino sketch for the ESP32 device, responsible for tracking workout data and sending it to the API.
- **`pyproject.toml`**: The project's configuration file, defining metadata and dependencies.
- **`docker-compose.yml`**: Defines the services, networks, and volumes for a Dockerized setup.
- **`Dockerfile`**: Instructions for building the Docker image for the application.
- **`README.md`**: The file you are currently reading.

## API Endpoints

All endpoints require an `x-api-key` header for authentication.

### Webhook
- `POST /webhook`: Logs fitness events sent from hardware devices.

### Analytics
- `GET /workouts`: Retrieves workout data, with options for date and device filtering.

### Balance Management
- `GET /balance`: Fetches the current point balance.
- `POST /withdraw`: Withdraws points from the balance.
- `POST /deposit`: Manually deposits points to the balance.
- `GET /transactions`: Retrieves a history of all transactions.

## Database

The application uses a SQLite database (`fitness_rewards.db`) with the following tables:

- **`workout_events`**: Stores individual fitness events from all connected devices.
- **`balance`**: Maintains the current point balance.
- **`transactions`**: Logs all deposits and withdrawals.

## Configuration

Key configurations are located in `server.py`:

- `DATABASE_URL`: The connection string for the SQLite database.
- `API_KEY`: The secret key for API authentication. **Remember to change this in a production environment.**

## Development and Testing

### Code Quality

Ensure your code adheres to quality standards by running the following commands:

```bash
# Format code
uv run black .

# Sort imports
uv run isort .

# Lint code
uv run flake8 .
```

### Running Tests

Execute the full test suite to verify functionality:
```bash
uv run pytest
```

For more detailed output, use the `-v` flag:
```bash
uv run pytest -v
```

You can also run specific test categories:
```bash
# Run authentication tests
uv run pytest test_server.py::TestAuthentication

# Run webhook endpoint tests
uv run pytest test_server.py::TestWebhookEndpoint
```

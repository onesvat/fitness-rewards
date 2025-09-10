# Hardware Components

This directory contains hardware-related code for the Fitness Rewards system.

## Elliptical Tracker

The `elliptical_tracker/` directory contains Arduino/ESP32 code for tracking elliptical machine usage.

### Files
- `elliptical_tracker.ino` - Main Arduino sketch for ESP32-based fitness tracker

### Setup
1. Install the ESP32 board package in Arduino IDE
2. Configure WiFi credentials in the sketch
3. Set the webhook URL to point to your Fitness Rewards API server
4. Upload to your ESP32 device

### Features
- Tracks exercise sessions (start, pause, resume, stop)
- Counts revolutions and sends data to the API
- Automatic WiFi reconnection
- Configurable timeouts for pause/stop detection

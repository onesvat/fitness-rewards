#!/usr/bin/env python3
"""
Home Assistant TV Consumer Script for Fitness Rewards API

Simple script that:
1. Checks Home Assistant TV/media player devices every X seconds
2. If a device is playing, withdraws points from the API
3. If balance is 0, pauses all playing devices

Commands:
- list: Show available media player devices in Home Assistant
- add <entity_id>: Add a device to monitoring list
- remove <entity_id>: Remove a device from monitoring list
- run: Start monitoring all configured devices
"""

import asyncio
import json
import logging
import os
import sys
import signal
from typing import Dict, List, Optional

import aiohttp

# Configuration
CONFIG_FILE = os.getenv("HA_CONFIG_FILE", "./data/ha_devices.json")
SERVER_URL = os.getenv("SERVER_URL", "http://server:8000")
API_KEY = os.getenv("API_KEY", "your-secret-api-key-123")
HA_URL = os.getenv("HA_URL", "http://homeassistant:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "your-ha-token")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))  # Check every 60 seconds
POINTS_PER_CHECK = int(os.getenv("POINTS_PER_CHECK", "1"))  # Charge 1 point per check

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ha_tv_consumer")

# Debug: Log configuration values
logger.info(f"Configuration loaded - SERVER_URL: {SERVER_URL}, API_KEY: {API_KEY[:10]}...")


class DeviceConfig:
    """Configuration for a monitored Home Assistant media player device."""

    def __init__(self, entity_id: str, name: str):
        self.entity_id = entity_id
        self.name = name

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DeviceConfig':
        return cls(
            entity_id=data["entity_id"],
            name=data["name"]
        )


class DeviceManager:
    """Manages the list of configured Home Assistant media player devices."""
    
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.devices: Dict[str, DeviceConfig] = {}
        self.load_config()
    
    def load_config(self):
        """Load device configuration from file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    for device_data in data.get("devices", []):
                        if "entity_id" not in device_data:
                            logger.warning(f"Skipping invalid device config (missing entity_id): {device_data}")
                            continue
                        if "name" not in device_data:
                            logger.warning(f"Skipping invalid device config (missing name): {device_data}")
                            continue
                        try:
                            config = DeviceConfig.from_dict(device_data)
                            self.devices[config.entity_id] = config
                        except Exception as e:
                            logger.error(f"Failed to load device {device_data}: {e}")
                logger.info(f"Loaded {len(self.devices)} devices from config")
            else:
                os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file {self.config_file}: {e}")
        except Exception as e:
            logger.error(f"Failed to load config from {self.config_file}: {e}")
    
    def save_config(self):
        """Save device configuration to file."""
        try:
            data = {
                "devices": [device.to_dict() for device in self.devices.values()]
            }
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.devices)} devices to config")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
    
    def add_device(self, entity_id: str, name: str):
        """Add a device to the configuration."""
        self.devices[entity_id] = DeviceConfig(entity_id, name)
        self.save_config()
    
    def remove_device(self, entity_id: str) -> bool:
        """Remove a device from the configuration."""
        if entity_id in self.devices:
            del self.devices[entity_id]
            self.save_config()
            return True
        return False


class APIClient:
    """Simple HTTP client for the Fitness Rewards API."""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
    
    async def _request(self, method: str, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make an HTTP request to the API."""
        headers = {"x-api-key": self.api_key}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method, 
                    f"{self.base_url}{path}", 
                    headers=headers, 
                    params=params
                ) as response:
                    if response.status >= 400:
                        text = await response.text()
                        logger.warning(f"API {method} {path} failed: {response.status} {text}")
                        return None
                    
                    if response.content_type == "application/json":
                        return await response.json()
                    return {}
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return None
    
    async def get_balance(self) -> int:
        """Get current balance, return 0 if failed."""
        result = await self._request("GET", "/balance")
        return result.get("balance", 1) if result else 1
    
    async def withdraw_points(self, count: int) -> bool:
        """Withdraw points from balance, return True if successful."""
        params = {"name": "tv_viewing", "count": count}
        result = await self._request("GET", "/withdraw", params)
        return result is not None


class HomeAssistantClient:
    """Client for communicating with Home Assistant API."""
    
    def __init__(self, url: str, token: str):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    async def _request(self, method: str, path: str, data: Optional[dict] = None) -> Optional[dict]:
        """Make an HTTP request to Home Assistant API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    f"{self.url}/api{path}",
                    headers=self.headers,
                    json=data
                ) as response:
                    if response.status >= 400:
                        text = await response.text()
                        logger.warning(f"HA API {method} {path} failed: {response.status} {text}")
                        return None
                    
                    if response.content_type == "application/json":
                        return await response.json()
                    return {}
        except Exception as e:
            logger.error(f"HA API request failed: {e}")
            return None
    
    async def get_states(self) -> List[dict]:
        """Get all entity states from Home Assistant."""
        result = await self._request("GET", "/states")
        return result if result else []
    
    async def get_state(self, entity_id: str) -> Optional[dict]:
        """Get state of a specific entity."""
        result = await self._request("GET", f"/states/{entity_id}")
        return result
    
    async def call_service(self, domain: str, service: str, entity_id: str) -> bool:
        """Call a Home Assistant service."""
        data = {"entity_id": entity_id}
        result = await self._request("POST", f"/services/{domain}/{service}", data)
        return result is not None


class DeviceMonitor:
    """Simple monitor for a single Home Assistant media player device."""
    
    def __init__(self, device_config: DeviceConfig, ha_client: HomeAssistantClient):
        self.config = device_config
        self.ha_client = ha_client
    
    async def is_playing(self) -> bool:
        """Check if device is currently playing content."""
        try:
            state = await self.ha_client.get_state(self.config.entity_id)
            if not state:
                return False
            
            # Check if the media player is in a playing state
            return state.get("state") == "playing"
            
        except Exception as e:
            logger.debug(f"Failed to get state for {self.config.name}: {e}")
            return False
    
    async def pause(self):
        """Pause playback on the device."""
        
        try:
            await self.ha_client.call_service("media_player", "media_pause", self.config.entity_id)
            logger.info(f"Paused {self.config.name}")
        except Exception as e:
            logger.error(f"Failed to pause {self.config.name}: {e}")


class HATVConsumer:
    """Main application class for Home Assistant TV monitoring."""
    
    def __init__(self):
        self.device_manager = DeviceManager(CONFIG_FILE)
        self.api_client = APIClient(SERVER_URL, API_KEY)
        self.ha_client = HomeAssistantClient(HA_URL, HA_TOKEN)
        self.monitors: List[DeviceMonitor] = []
        self.running = False
    
    async def list_devices(self):
        """List available media player devices in Home Assistant."""
        print("Getting media player devices from Home Assistant...")
        try:
            states = await self.ha_client.get_states()
            media_players = [
                state for state in states 
                if state.get("entity_id", "").startswith("media_player.")
            ]
            
            if not media_players:
                print("No media player devices found.")
                return
            
            print(f"\nFound {len(media_players)} media player(s):")
            print("-" * 80)
            print(f"{'Name':<30} {'Entity ID':<30} {'State':<10} {'Configured':<10}")
            print("-" * 80)
            
            for device in media_players:
                entity_id = device.get("entity_id", "")
                name = device.get("attributes", {}).get("friendly_name", entity_id)
                state = device.get("state", "unknown")
                configured = "Yes" if entity_id in self.device_manager.devices else "No"
                print(f"{name:<30} {entity_id:<30} {state:<10} {configured:<10}")
            
            print("\nTo add a device: python ha_tv_consumer.py add <entity_id>")
            
        except Exception as e:
            print(f"Error getting devices: {e}")
    
    def add_device(self, entity_id: str):
        """Add a device to the configuration."""
        if entity_id in self.device_manager.devices:
            print(f"Device {entity_id} already configured.")
            return
        
        async def _add():
            state = await self.ha_client.get_state(entity_id)
            if not state:
                print(f"Device {entity_id} not found in Home Assistant.")
                return
            
            name = state.get("attributes", {}).get("friendly_name", entity_id)
            self.device_manager.add_device(entity_id, name)
            print(f"Added: {name} ({entity_id})")
        
        asyncio.run(_add())
    
    def remove_device(self, entity_id: str):
        """Remove a device from the configuration."""
        if self.device_manager.remove_device(entity_id):
            print(f"Removed: {entity_id}")
        else:
            print(f"Device {entity_id} not found.")
    
    async def run_monitoring(self):
        """Main monitoring loop - check devices and charge points."""
        if not self.device_manager.devices:
            print("No devices configured. Use 'list' and 'add' commands first.")
            return
        
        print(f"Starting monitoring for {len(self.device_manager.devices)} device(s)...")
        print(f"Checking every {CHECK_INTERVAL} seconds, charging {POINTS_PER_CHECK} point(s) per playing device")
        
        # Create monitors
        self.monitors = [
            DeviceMonitor(device, self.ha_client) 
            for device in self.device_manager.devices.values()
        ]
        
        # Use event for clean shutdown
        shutdown_event = asyncio.Event()
        
        # Handle shutdown
        def signal_handler():
            logger.info("Shutdown signal received")
            shutdown_event.set()
        
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
        
        try:
            while not shutdown_event.is_set():
                # Check balance first
                balance = await self.api_client.get_balance()
                logger.info(f"Current balance: {balance} points")
                
                if balance <= 0:
                    logger.warning("No balance! Pausing all devices...")
                    for monitor in self.monitors:
                        await monitor.pause()
                    # Wait with cancellation support
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=CHECK_INTERVAL)
                        break
                    except asyncio.TimeoutError:
                        continue
                
                # Check each device
                playing_devices = []
                for monitor in self.monitors:
                    if await monitor.is_playing():
                        playing_devices.append(monitor.config.name)
                
                # Charge points for playing devices
                if playing_devices:
                    total_charge = len(playing_devices) * POINTS_PER_CHECK
                    logger.info(f"Playing devices: {', '.join(playing_devices)}")
                    
                    if await self.api_client.withdraw_points(total_charge):
                        logger.info(f"Charged {total_charge} points")
                    else:
                        logger.warning("Failed to charge points - pausing all devices")
                        for monitor in self.monitors:
                            await monitor.pause()
                
                # Wait with cancellation support
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=CHECK_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    pass
                
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            logger.info("Shutting down...")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python ha_tv_consumer.py list")
        print("  python ha_tv_consumer.py add <entity_id>")
        print("  python ha_tv_consumer.py remove <entity_id>")
        print("  python ha_tv_consumer.py run")
        sys.exit(1)
    
    consumer = HATVConsumer()
    command = sys.argv[1].lower()
    
    if command == "list":
        asyncio.run(consumer.list_devices())
    elif command == "add":
        if len(sys.argv) < 3:
            print("Usage: python ha_tv_consumer.py add <entity_id>")
            sys.exit(1)
        consumer.add_device(sys.argv[2])
    elif command == "remove":
        if len(sys.argv) < 3:
            print("Usage: python ha_tv_consumer.py remove <entity_id>")
            sys.exit(1)
        consumer.remove_device(sys.argv[2])
    elif command == "run":
        asyncio.run(consumer.run_monitoring())
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
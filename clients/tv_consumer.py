#!/usr/bin/env python3
"""
TV Consumer Script for Fitness Rewards API

Simple script that:
1. Checks Apple TV devices every X seconds
2. If a device is playing, withdraws points from the API
3. If balance is 0, pauses all playing devices

Commands:
- list: Show available Apple TV devices on the network
- add <identifier>: Add a device to monitoring list
- remove <identifier>: Remove a device from monitoring list
- run: Start monitoring all configured devices
"""

import asyncio
import json
import logging
import os
import sys
import signal
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path

import aiohttp
from pyatv import scan, connect, const, exceptions

# Configuration
CONFIG_FILE = os.getenv("TV_CONFIG_FILE", "./data/tv_devices.json")
API_BASE = os.getenv("API_BASE", "http://server:8000")
API_KEY = os.getenv("API_KEY", "your-secret-api-key-123")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))  # Check every 60 seconds
POINTS_PER_CHECK = int(os.getenv("POINTS_PER_CHECK", "1"))  # Charge 1 point per check

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("tv_consumer")


class DeviceConfig:
    """Configuration for a monitored Apple TV device."""
    
    def __init__(self, identifier: str, name: str, address: str):
        self.identifier = identifier
        self.name = name
        self.address = address
    
    def to_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "name": self.name,
            "address": self.address
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DeviceConfig':
        return cls(
            identifier=data["identifier"],
            name=data["name"],
            address=data["address"]
        )


class DeviceManager:
    """Manages the list of configured Apple TV devices."""
    
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
                        config = DeviceConfig.from_dict(device_data)
                        self.devices[config.identifier] = config
                logger.info(f"Loaded {len(self.devices)} devices from config")
            else:
                os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    
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
    
    def add_device(self, identifier: str, name: str, address: str):
        """Add a device to the configuration."""
        self.devices[identifier] = DeviceConfig(identifier, name, address)
        self.save_config()
    
    def remove_device(self, identifier: str) -> bool:
        """Remove a device from the configuration."""
        if identifier in self.devices:
            del self.devices[identifier]
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
        return result.get("balance", 0) if result else 0
    
    async def withdraw_points(self, count: int) -> bool:
        """Withdraw points from balance, return True if successful."""
        params = {"name": "tv_viewing", "count": count}
        result = await self._request("GET", "/withdraw", params)
        return result is not None


class DeviceMonitor:
    """Simple monitor for a single Apple TV device."""
    
    def __init__(self, device_config: DeviceConfig):
        self.config = device_config
        self.atv = None
    
    async def connect(self) -> bool:
        """Connect to the Apple TV device."""
        try:
            loop = asyncio.get_running_loop()
            devices = await scan(loop, timeout=5)
            for device in devices:
                if (device.identifier == self.config.identifier or 
                    device.address.exploded == self.config.address):
                    self.atv = await connect(device)
                    logger.info(f"Connected to {self.config.name}")
                    return True
            
            logger.warning(f"Device {self.config.name} not found")
            return False
            
        except Exception as e:
            logger.error(f"Failed to connect to {self.config.name}: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the device."""
        if self.atv:
            await self.atv.close()
            self.atv = None
    
    async def is_playing(self) -> bool:
        """Check if device is currently playing content."""
        try:
            if not self.atv:
                return False
            
            playing = await self.atv.metadata.playing()
            state = playing.play_state.name if playing.play_state else None
            return state == "Playing"
            
        except Exception as e:
            logger.debug(f"Failed to get playback state for {self.config.name}: {e}")
            return False
    
    async def pause(self):
        """Pause playback on the device."""
        try:
            if self.atv and self.atv.remote_control:
                await self.atv.remote_control.pause()
                logger.info(f"Paused {self.config.name}")
        except Exception as e:
            logger.error(f"Failed to pause {self.config.name}: {e}")


class TVConsumer:
    """Main application class - simple and straightforward."""
    
    def __init__(self):
        self.device_manager = DeviceManager(CONFIG_FILE)
        self.api_client = APIClient(API_BASE, API_KEY)
        self.monitors: List[DeviceMonitor] = []
        self.running = False
    
    async def list_devices(self):
        """List available Apple TV devices on the network."""
        print("Scanning for Apple TV devices...")
        try:
            loop = asyncio.get_running_loop()
            devices = await scan(loop, timeout=10)
            if not devices:
                print("No Apple TV devices found.")
                return
            
            print(f"\nFound {len(devices)} device(s):")
            print("-" * 70)
            print(f"{'Name':<25} {'Identifier':<20} {'Configured':<10}")
            print("-" * 70)
            
            for device in devices:
                configured = "Yes" if device.identifier in self.device_manager.devices else "No"
                print(f"{device.name:<25} {device.identifier:<20} {configured:<10}")
            
            print("\nTo add a device: python tv_consumer.py add <identifier>")
            
        except Exception as e:
            print(f"Error scanning: {e}")
    
    def add_device(self, identifier: str):
        """Add a device to the configuration."""
        if identifier in self.device_manager.devices:
            print(f"Device {identifier} already configured.")
            return
        
        async def _add():
            loop = asyncio.get_running_loop()
            devices = await scan(loop, timeout=10)
            for device in devices:
                if device.identifier == identifier:
                    self.device_manager.add_device(
                        identifier=device.identifier,
                        name=device.name,
                        address=device.address.exploded
                    )
                    print(f"Added: {device.name}")
                    return
            print(f"Device {identifier} not found.")
        
        asyncio.run(_add())
    
    def remove_device(self, identifier: str):
        """Remove a device from the configuration."""
        if self.device_manager.remove_device(identifier):
            print(f"Removed: {identifier}")
        else:
            print(f"Device {identifier} not found.")
    
    async def run_monitoring(self):
        """Main monitoring loop - check devices and charge points."""
        if not self.device_manager.devices:
            print("No devices configured. Use 'list' and 'add' commands first.")
            return
        
        print(f"Starting monitoring for {len(self.device_manager.devices)} device(s)...")
        print(f"Checking every {CHECK_INTERVAL} seconds, charging {POINTS_PER_CHECK} point(s) per playing device")
        
        # Create monitors
        self.monitors = [DeviceMonitor(device) for device in self.device_manager.devices.values()]
        self.running = True
        
        # Handle shutdown
        def signal_handler():
            logger.info("Shutdown signal received")
            self.running = False
        
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
        
        try:
            while self.running:
                # Check balance first
                balance = await self.api_client.get_balance()
                logger.info(f"Current balance: {balance} points")
                
                if balance <= 0:
                    logger.warning("No balance! Pausing all devices...")
                    for monitor in self.monitors:
                        if monitor.atv:
                            await monitor.pause()
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # Check each device
                playing_devices = []
                for monitor in self.monitors:
                    # Connect if needed
                    if not monitor.atv:
                        await monitor.connect()
                    
                    # Check if playing
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
                            if monitor.atv:
                                await monitor.pause()
                
                await asyncio.sleep(CHECK_INTERVAL)
                
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            # Cleanup
            logger.info("Shutting down...")
            for monitor in self.monitors:
                await monitor.disconnect()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python tv_consumer.py list")
        print("  python tv_consumer.py add <identifier>")
        print("  python tv_consumer.py remove <identifier>")
        print("  python tv_consumer.py run")
        sys.exit(1)
    
    consumer = TVConsumer()
    command = sys.argv[1].lower()
    
    if command == "list":
        asyncio.run(consumer.list_devices())
    elif command == "add":
        if len(sys.argv) < 3:
            print("Usage: python tv_consumer.py add <identifier>")
            sys.exit(1)
        consumer.add_device(sys.argv[2])
    elif command == "remove":
        if len(sys.argv) < 3:
            print("Usage: python tv_consumer.py remove <identifier>")
            sys.exit(1)
        consumer.remove_device(sys.argv[2])
    elif command == "run":
        asyncio.run(consumer.run_monitoring())
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()

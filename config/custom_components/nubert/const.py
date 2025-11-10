"""Constants for the Nubert integration."""

from typing import Final

DOMAIN: Final = "nubert"

# Configuration
CONF_DEVICE: Final = "device"

# Default Values
DEFAULT_NAME: Final = "Nubert Speaker"

# Bluetooth specifics
CONTROL_SERVICE_UUID: Final = "8e2ceaaa-0e27-11e7-93ae-92361f002671"
SERVICE_UUID: Final = "0000a600-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID: Final = "8e2cece4-0e27-11e7-93ae-92361f002671"

# Update intervals
SCAN_INTERVAL: Final = 30  # How often to poll for state updates in seconds

# Supported features/commands
SUPPORTED_COMMANDS = {
    "power",
    "volume",
    "source",
}  # Update with actual supported commands

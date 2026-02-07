"""Falcon BMS Key File Parser for use with Joystick Diagrams"""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid5, NAMESPACE_DNS

from joystick_diagrams.exceptions import JoystickDiagramsError
from joystick_diagrams.input.axis import Axis, AxisDirection, AxisSlider
from joystick_diagrams.input.button import Button
from joystick_diagrams.input.device import Device_
from joystick_diagrams.input.hat import Hat, HatDirection
from joystick_diagrams.input.profile import Profile_
from joystick_diagrams.input.profile_collection import ProfileCollection

_logger = logging.getLogger(__name__)

# Falcon BMS button ID mapping patterns
BUTTON_PATTERN = "BUTTON_"
POV_PATTERN = "POV_"
AXIS_PATTERN = "AXIS_"

# HAT direction mapping
HAT_DIRECTION_MAP = {
    "U": HatDirection.U,
    "UR": HatDirection.UR,
    "R": HatDirection.R,
    "DR": HatDirection.DR,
    "D": HatDirection.D,
    "DL": HatDirection.DL,
    "L": HatDirection.L,
    "UL": HatDirection.UL,
}

# Axis direction mapping
AXIS_DIRECTION_MAP = {
    "X": AxisDirection.X,
    "Y": AxisDirection.Y,
    "Z": AxisDirection.Z,
    "RX": AxisDirection.RX,
    "RY": AxisDirection.RY,
    "RZ": AxisDirection.RZ,
}

# Falcon BMS namespace for generating UUIDs
FALCON_BMS_NAMESPACE = uuid5(NAMESPACE_DNS, "falcon-bms.localhost")


class FalconBMSParser:
    """Parser for Falcon BMS key configuration files"""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.data = self._load_file()
        self.profiles = ProfileCollection()

    def _load_file(self) -> dict[str, Any]:
        """Load and parse the BMS key file"""
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Check file extension to determine format
            if self.file_path.suffix == ".json" or self.file_path.name.endswith("mappings.json"):
                # Parse as JSON format (for mappings.json or explicit .json files)
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    _logger.error(f"Failed to parse JSON: {e}")
                    raise JoystickDiagramsError(f"Failed to parse JSON file: {e}") from e
            else:
                # Parse as Falcon BMS key file format (.key or .auto.key)
                _logger.debug(f"Parsing as Falcon BMS key format: {self.file_path.suffix}")
                return self._parse_text_format(content)
        except Exception as e:
            _logger.error(f"Error loading BMS file: {e}")
            raise JoystickDiagramsError(f"Failed to parse BMS file: {e}") from e

    def _parse_text_format(self, content: str) -> dict[str, Any]:
        """Parse Falcon BMS key file format
        
        BMS key files contain command mappings organized by device sections marked with:
        #======== DEVICE NAME ========
        
        Followed by mappings in the format:
        CommandName DeviceID Unknown HexKeyCode Mod1 Mod2 Mod3 Mode "Description"
        
        Example:
        #======== WINWING Orion Joystick Base 2  JGRIP-F16 ========
        SimOverHeat 312 0 0x3B 1 0 0 1 "TEST: FIRE & OHEAT DETECT Button - Hold"
        """
        import re
        
        data = {"profiles": [{"profile_name": "Falcon BMS", "devices": {}}]}
        devices = {}
        current_device_name = None
        current_device_uuid = None
        
        # Pattern to match device headers
        device_header_pattern = r'#=+\s+(.+?)\s+=+#?'
        
        for line in content.strip().split('\n'):
            line_stripped = line.strip()
            
            # Skip empty lines
            if not line_stripped:
                continue
            
            # Check for device header lines
            if line_stripped.startswith('#'):
                # Try to extract device name from header
                match = re.match(device_header_pattern, line_stripped)
                if match:
                    device_name = match.group(1).strip()
                    # Skip generic section headers that aren't devices
                    if device_name and not device_name.startswith('==='):
                        # Extract base device name (remove POV variants)
                        # e.g., "WINWING ... : POV #0" -> "WINWING ..."
                        base_device_name = re.sub(r'\s*:\s*POV\s*#\d+\s*$', '', device_name, flags=re.IGNORECASE)
                        
                        current_device_name = base_device_name
                        # Generate UUID based on base device name
                        current_device_uuid = str(uuid5(FALCON_BMS_NAMESPACE, f"device_{base_device_name}"))
                        
                        # Create device entry if not exists
                        if current_device_uuid not in devices:
                            devices[current_device_uuid] = {
                                "guid": current_device_uuid,
                                "name": base_device_name,
                                "inputs": {
                                    "buttons": [],
                                    "axis": [],
                                    "axis_slider": [],
                                    "hats": []
                                }
                            }
                continue
            
            # Skip lines with REM: prefix (remarks)
            if 'REM:' in line_stripped:
                continue
            
            # Skip section headers (SimDoNothing with FFFFFFFF key)
            if 'SimDoNothing' in line_stripped and '0XFFFFFFFF' in line_stripped.upper():
                continue
            
            try:
                # Split the line - format: Command DeviceID Unknown HexKey Mod1 Mod2 Mod3 Mode "Description"
                parts = line_stripped.split('"')
                if len(parts) < 2:
                    continue
                
                description = parts[1]  # Text between quotes
                params = parts[0].strip().split()
                
                if len(params) < 4:
                    _logger.debug(f"Skipping line with insufficient fields: {line_stripped}")
                    continue
                
                command_name = params[0]
                device_id = params[1]
                hex_key = params[3]
                modifiers = params[4:8] if len(params) >= 8 else []
                
                # Determine which device this belongs to
                target_device_uuid = current_device_uuid
                target_device_name = current_device_name
                
                # If no current device, use the device_id to create one
                if not target_device_uuid:
                    target_device_name = f"Falcon BMS Device {device_id}"
                    target_device_uuid = str(uuid5(FALCON_BMS_NAMESPACE, f"device_{device_id}"))
                
                # Ensure device exists
                if target_device_uuid not in devices:
                    devices[target_device_uuid] = {
                        "guid": target_device_uuid,
                        "name": target_device_name,
                        "inputs": {
                            "buttons": [],
                            "axis": [],
                            "axis_slider": [],
                            "hats": []
                        }
                    }
                
                # Convert hex key to a button ID
                try:
                    key_value = int(hex_key, 16)
                    button_id = f"BUTTON_{key_value}"
                    
                    # Create the input mapping
                    input_data = {
                        "id": button_id,
                        "command": description,
                        "modifiers": modifiers
                    }
                    
                    # Add to buttons (default to buttons, could extend for axes/hats)
                    devices[target_device_uuid]["inputs"]["buttons"].append(input_data)
                    
                except (ValueError, TypeError) as e:
                    _logger.warning(f"Failed to parse hex key {hex_key}: {e}")
                    continue
                    
            except (IndexError, ValueError) as e:
                _logger.debug(f"Failed to parse line: {line_stripped} - {e}")
                continue
        
        # Convert devices dict to list
        data["profiles"][0]["devices"] = list(devices.values())
        
        if not devices:
            _logger.warning("No valid input mappings found in BMS key file")
            return {"profiles": []}
        
        _logger.info(f"Parsed {len(devices)} devices from BMS key file")
        return data

    def process_profiles(self) -> ProfileCollection:
        """Process all profiles from the loaded data"""
        if "profiles" not in self.data:
            _logger.warning("No profiles found in BMS data")
            return self.profiles

        for profile_data in self.data["profiles"]:
            self._process_profile(profile_data)

        return self.profiles

    def _process_profile(self, profile_data: dict[str, Any]) -> None:
        """Process a single profile from the configuration"""
        profile_name = profile_data.get("profile_name", "Default")
        profile = self.profiles.create_profile(profile_name)

        devices = profile_data.get("devices", [])
        for device_data in devices:
            self._process_device(profile, device_data)

    def _process_device(self, profile: Profile_, device_data: dict[str, Any]) -> None:
        """Process a single device configuration"""
        device_guid = device_data.get("guid", "")
        device_name = device_data.get("name", "Unknown Device")

        device = profile.add_device(device_guid, device_name)

        inputs = device_data.get("inputs", {})

        # Process buttons
        buttons = inputs.get("buttons", [])
        for button_data in buttons:
            self._process_button(device, button_data)

        # Process axes
        axes = inputs.get("axis", [])
        for axis_data in axes:
            self._process_axis(device, axis_data)

        # Process axis sliders
        axis_sliders = inputs.get("axis_slider", [])
        for slider_data in axis_sliders:
            self._process_slider(device, slider_data)

        # Process hats (POV)
        hats = inputs.get("hats", [])
        for hat_data in hats:
            self._process_hat(device, hat_data)

    def _process_button(self, device: Device_, button_data: dict[str, Any]) -> None:
        """Process a button input"""
        button_id = button_data.get("id", "")
        command = button_data.get("command", "")

        if not button_id or not command:
            return

        try:
            # Extract button number from ID (e.g., "BUTTON_0" -> 0)
            if button_id.startswith(BUTTON_PATTERN):
                button_num = int(button_id.replace(BUTTON_PATTERN, ""))
                button = Button(button_num)
                device.create_input(button, command)
            else:
                _logger.warning(f"Unknown button format: {button_id}")
        except (ValueError, IndexError) as e:
            _logger.warning(f"Failed to parse button {button_id}: {e}")

    def _process_axis(self, device: Device_, axis_data: dict[str, Any]) -> None:
        """Process an axis input"""
        axis_id = axis_data.get("id", "")
        command = axis_data.get("command", "")

        if not axis_id or not command:
            return

        try:
            # Extract axis type from ID (e.g., "AXIS_X" -> X)
            if axis_id.startswith(AXIS_PATTERN):
                axis_type = axis_id.replace(AXIS_PATTERN, "")
                if axis_type in AXIS_DIRECTION_MAP:
                    axis = Axis(AXIS_DIRECTION_MAP[axis_type])
                    device.create_input(axis, command)
                else:
                    _logger.warning(f"Unknown axis type: {axis_type}")
        except (ValueError, KeyError) as e:
            _logger.warning(f"Failed to parse axis {axis_id}: {e}")

    def _process_slider(self, device: Device_, slider_data: dict[str, Any]) -> None:
        """Process an axis slider input"""
        slider_id = slider_data.get("id", "")
        command = slider_data.get("command", "")

        if not slider_id or not command:
            return

        try:
            # Extract slider number from ID (e.g., "SLIDER_0" -> 0)
            if slider_id.startswith("SLIDER_"):
                slider_num = int(slider_id.replace("SLIDER_", ""))
                slider = AxisSlider(slider_num)
                device.create_input(slider, command)
        except (ValueError, IndexError) as e:
            _logger.warning(f"Failed to parse slider {slider_id}: {e}")

    def _process_hat(self, device: Device_, hat_data: dict[str, Any]) -> None:
        """Process a hat (POV) input"""
        hat_id = hat_data.get("id", "")
        command = hat_data.get("command", "")

        if not hat_id:
            return

        try:
            # Extract hat info from ID (e.g., "POV_1_D" -> hat_id=1, direction=D)
            if hat_id.startswith(POV_PATTERN):
                parts = hat_id.replace(POV_PATTERN, "").split("_")
                if len(parts) >= 2:
                    hat_num = int(parts[0])
                    direction_str = parts[1]

                    if direction_str in HAT_DIRECTION_MAP:
                        hat = Hat(hat_num, HAT_DIRECTION_MAP[direction_str])
                        device.create_input(hat, command if command else "")
                    else:
                        _logger.warning(f"Unknown hat direction: {direction_str}")
            else:
                _logger.warning(f"Unknown hat format: {hat_id}")
        except (ValueError, IndexError) as e:
            _logger.warning(f"Failed to parse hat {hat_id}: {e}")


def parse_bms_file(file_path: Path) -> ProfileCollection:
    """Convenience function to parse a BMS file and return ProfileCollection"""
    parser = FalconBMSParser(file_path)
    return parser.process_profiles()

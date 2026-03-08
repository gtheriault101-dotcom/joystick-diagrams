"""
================================================================================
Falcon BMS Plugin for Joystick-Diagrams
================================================================================
Author  : Generated for use with https://github.com/Rexeh/joystick-diagrams
Target  : Falcon BMS 4.38+ (tested against 4.38.1)
Purpose : Parse Falcon BMS joystick XML configuration files (JoyAssgn XML)
          and the AUTO.KEY callback label file from USER/Config, then emit
          the data structures that Joystick-Diagrams expects so that device
          diagrams can be rendered with correct button/axis/POV labels.

Architecture overview
---------------------
Falcon BMS stores joystick assignments in per-device XML files:
    <BMS_ROOT>/User/Config/Setup.v100.<DeviceName> {GUID}.xml

Each XML file contains three main sections:
    <axis>  – axes assigned to simulator functions
    <pov>   – POV hat switch directions (up to 4 POVs × 8 directions each)
    <dx>    – DirectX button assignments (up to 128 buttons)

BMS 4.38.1 quirk: the Windows DirectX button number stored in the XML is
the ACTUAL button index + 1.  We subtract 1 when converting back to
zero-based DX numbering for Joystick-Diagrams.

The callback names (e.g., "SimTMSUp") are translated to human-readable
labels by looking them up in the AUTO.KEY file:
    <BMS_ROOT>/User/Config/falconbms.key  (or auto.key / key file)

AUTO.KEY format (space-delimited columns):
    Callback  JoystickID  -1  DeviceIndex  Modifiers  SoundID  ...
    OR (for keyboard-only entries):
    Callback  -1  0  0XFFFFFFFF  0  0  0  Priority  "Description"

The quoted description on keyboard-only lines is the best human label.
For joystick lines (no quoted description), we clean the Callback name
by stripping redundant prefixes (Sim, OTW, AF, SetRight, SetLeft).
================================================================================
"""

from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from joystick_diagrams.input.profile_collection import ProfileCollection
import uuid

# ---------------------------------------------------------------------------
# Logger for the plugin – use the module name so it integrates cleanly with
# the Joystick-Diagrams logging hierarchy.
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ===========================================================================
#  CONSTANTS
# ===========================================================================

# Prefixes that Falcon BMS prepends to callback names but carry no
# human-readable information for a HOTAS diagram label.
CALLBACK_STRIP_PREFIXES: tuple[str, ...] = (
    "SimDoNothing",   # Must check this FIRST (full match → skip entirely)
)

CALLBACK_TRIM_PREFIXES: tuple[str, ...] = (
    "SetRightThrottle",
    "SetLeftThrottle",
    "OTW",            # Out-The-Window view commands
    "AF",             # Aircraft / airframe commands
    "Sim",            # Simulator commands (most callbacks)
    "AWACS",          # AWACS radio commands
    "Toggle",         # Toggle commands
    "FOV",            # Field-of-view commands
    "Recenter",       # Head-tracking
)

# Maximum DX buttons per device in BMS
MAX_DX_BUTTONS: int = 128

# Maximum POV hats per device
MAX_POV_HATS: int = 4

# Number of directions per POV hat (N, NE, E, SE, S, SW, W, NW)
POV_DIRECTIONS: int = 8

# Map POV direction index → compass label for diagram output
POV_DIRECTION_LABELS: dict[int, str] = {
    0: "N",
    1: "NE",
    2: "E",
    3: "SE",
    4: "S",
    5: "SW",
    6: "W",
    7: "NW",
}

# BMS 4.38.1: stored DX number = real DX index + 1
BMS_DX_OFFSET: int = 1

# Patterns used to extract a short device name from the XML filename.
# e.g. "Setup.v100.Simgears ICP LT IT {CC9D52E0-...}.xml" → "Simgears ICP LT IT"
FILENAME_DEVICE_PATTERN: re.Pattern = re.compile(
    r"Setup\.v\d+\.(.*?)\s*\{[0-9A-Fa-f\-]+\}\.xml$",
    re.IGNORECASE,
)

# Well-known short labels: if any of these substrings are found in the
# extracted device name, truncate TO that keyword.
DEVICE_SHORT_LABELS: tuple[str, ...] = (
    "Joystick",
    "Throttle",
    "ICP",
    "Rudder_Pedal",
    "MFD_1",
    "MFD_2",
    "MFD_3",
)


# ===========================================================================
#  DATA CLASSES  (mirrors the Joystick-Diagrams internal model)
# ===========================================================================

@dataclass
class AxisAssignment:
    """Represents a single axis binding on a HOTAS device."""
    axis_index: int          # Zero-based axis index on the device
    axis_name: str           # BMS axis name, e.g. "HUD_Brightness"
    label: str               # Human-readable label for the diagram
    invert: bool = False
    saturation: Optional[str] = None
    deadzone: Optional[str] = None


@dataclass
class PovDirection:
    """A single direction within a POV hat."""
    direction_index: int     # 0=N, 1=NE, 2=E, … 7=NW
    direction_label: str     # "N", "NE", etc.
    callbacks: list[str] = field(default_factory=list)
    label: str = ""          # Human-readable label after lookup


@dataclass
class PovAssignment:
    """One POV hat switch with up to 8 directional bindings."""
    pov_index: int           # 0-based hat index
    directions: list[PovDirection] = field(default_factory=list)


@dataclass
class ButtonAssignment:
    """One DirectX button with up to 4 modifier-shift-state callbacks."""
    dx_index: int            # Zero-based DX index (BMS stored value − 1)
    callbacks: list[str] = field(default_factory=list)   # Raw callback names
    label: str = ""          # Human-readable label after lookup


@dataclass
class DeviceProfile:
    def __init__(self, name: str, source_file: Path):
        """All bindings for one physical device extracted from one XML file."""
        self.source_file: Path  = source_file                           # Original XML path
        self.axes: list[AxisAssignment] = field(default_factory=list)
        self.povs: list[PovAssignment] = field(default_factory=list)
        self.buttons: list[ButtonAssignment] = field(default_factory=list)
        self.guid: Optional[str] = str(uuid.uuid4())                    # Extracted from filename if possible
        self.name: Optional[str] = name                      # Optional user-friendly name


# ===========================================================================
#  AUTO.KEY PARSER
# ===========================================================================

class AutoKeyParser:
    """
    Parses the Falcon BMS AUTO.KEY (or falconbms.key) file to build a
    lookup table:   callback_name  →  human_readable_label

    AUTO.KEY line formats
    ---------------------
    Keyboard-only assignment (has a quoted description at the end):
        FlightEchelonRight -1 0 0XFFFFFFFF 0 0 0 1 "FLIGHT: Go Echolon Left"

    Joystick assignment (no quoted description, device index ≥ 0):
        SimTMSUp 159 -1 -2 0 0x0 -1

    Comment lines start with '#'.
    Lines containing "SimDoNothing" as the callback are ignored.

    Label selection priority
    ------------------------
    1. If a quoted description exists, use it (strip the surrounding quotes
       and take the portion after the last ': ' for brevity, or the full
       string if no colon).
    2. Otherwise, clean the callback name:
       - Strip known redundant prefixes (Sim, OTW, AF, …)
       - Insert spaces before CamelCase word boundaries for readability
       - e.g. "SimTMSUp" → "TMS Up"
    """

    def __init__(self, key_file_path: Path):
        self.key_file_path = key_file_path
        # Main lookup: callback_name (case-sensitive) → label string
        self.callback_labels: dict[str, str] = {}
        self._parse()

    # ------------------------------------------------------------------
    def _parse(self) -> None:
        """Read the key file and populate self.callback_labels."""
        if not self.key_file_path.exists():
            logger.warning(
                "AUTO.KEY file not found at '%s'. "
                "Callback names will be used as-is.",
                self.key_file_path,
            )
            return

        logger.info("Parsing AUTO.KEY: %s", self.key_file_path)

        with open(self.key_file_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                self._process_line(line.strip())

        logger.info(
            "Loaded %d callback labels from AUTO.KEY.", len(self.callback_labels)
        )

    # ------------------------------------------------------------------
    def _process_line(self, line: str) -> None:
        """Parse one line from the key file."""
        # Skip empty lines and comment lines
        if not line or line.startswith("#"):
            return

        # Tokenise – split on whitespace but keep quoted strings intact
        tokens = line.split()
        if not tokens:
            return

        callback_name = tokens[0]

        # Skip no-op callbacks entirely
        if callback_name == "SimDoNothing":
            return

        # Extract quoted description if present (keyboard-only lines)
        quoted_match = re.search(r'"([^"]+)"', line)
        if quoted_match:
            description = quoted_match.group(1)
            # Take the shortest, most meaningful portion:
            # If the description has ": " use the part after the LAST colon.
            if ": " in description:
                label = description.split(": ", 1)[-1].strip()
            else:
                label = description.strip()
        else:
            # No description: derive label from callback name
            label = clean_callback_name(callback_name)

        # Only store the first occurrence; later lines for the same callback
        # may be joystick-device-specific duplicates.
        if callback_name not in self.callback_labels:
            self.callback_labels[callback_name] = label

    # ------------------------------------------------------------------
    def get_label(self, callback_name: str) -> str:
        """
        Return the human-readable label for a callback name.
        Falls back to a cleaned version of the callback name if not found.
        """
        return self.callback_labels.get(
            callback_name, clean_callback_name(callback_name)
        )


# ===========================================================================
#  UTILITY FUNCTIONS
# ===========================================================================

def clean_callback_name(callback: str) -> str:
    """
    Strip redundant BMS prefixes from a callback name and convert
    CamelCase to Title Case with spaces.

    Examples
    --------
    "SimTMSUp"          → "TMS Up"
    "OTWViewLeft"       → "View Left"
    "AFGearDown"        → "Gear Down"
    "SimICPCom1"        → "ICP Com 1"
    "SetRightThrottle…" → "Throttle…"
    "SimDoNothing"      → "" (caller should skip)
    """
    if callback == "SimDoNothing":
        return ""

    cleaned = callback

    # Strip each known prefix in order (longest first to avoid partial matches)
    for prefix in sorted(CALLBACK_TRIM_PREFIXES, key=len, reverse=True):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break  # Only strip one prefix

    # Insert spaces before uppercase letters that follow lowercase letters or
    # before sequences of capitals that precede a lowercase letter.
    # "TMSUp" → "TMS Up"
    # "GearDown" → "Gear Down"
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cleaned)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)

    # Normalise multiple spaces
    return re.sub(r"\s+", " ", spaced).strip()


def extract_device_name(xml_filename: str) -> str:
    """
    Derive a clean device label from the BMS XML filename.

    BMS filenames follow this pattern:
        Setup.v100.<DeviceName> {GUID}.xml

    We extract <DeviceName>, then check if it contains a well-known short
    label (Joystick, Throttle, ICP, etc.) and truncate to just that.

    Examples
    --------
    "Setup.v100.Simgears ICP LT IT {CC9D52E0-...}.xml"  → "Simgears ICP LT IT"
    "Setup.v100.F16 MFD 1 {36EE15C0-...}.xml"           → "F16 MFD 1"
    "Setup.v100.Thrustmaster Joystick {XXXX}.xml"        → "Joystick"
    """
    match = FILENAME_DEVICE_PATTERN.match(xml_filename)
    if not match:
        # Fallback: strip the common prefix if regex doesn't match
        name = xml_filename.replace("Setup.v100.", "").strip()
        # Remove trailing GUID
        name = re.sub(r"\s*\{[0-9A-Fa-f\-]+\}\.xml$", "", name, flags=re.IGNORECASE)
        return name or xml_filename

    name = match.group(1).strip()

    # Check for known short labels; if found, truncate TO that label.
    name_upper = name.upper()
    for short_label in DEVICE_SHORT_LABELS:
        if short_label.upper() in name_upper:
            # Return everything from the short label onward in the original string
            idx = name_upper.index(short_label.upper())
            return name[idx:]

    return name


# ===========================================================================
#  XML PARSER FOR BMS JoyAssgn FILES
# ===========================================================================

class BmsXmlParser:
    """
    Parses one Falcon BMS JoyAssgn XML file and extracts axis, POV and
    button assignment data into a DeviceProfile.

    BMS 4.38.1 DX index correction
    --------------------------------
    The <DxAssgn> elements are listed in sequence starting at index 0.
    The i-th <DxAssgn> corresponds to BMS internal button number (i + 1)
    but maps to DirectX button index i (zero-based) as used by Windows and
    Joystick-Diagrams.  We therefore use the list position directly.
    """

    def __init__(self, xml_path: Path, auto_key_parser: AutoKeyParser):
        self.xml_path = xml_path
        self.auto_key = auto_key_parser
        self.name = extract_device_name(xml_path.name)

    # ------------------------------------------------------------------
    def parse(self) -> Optional[DeviceProfile]:
        """
        Parse the XML file and return a populated DeviceProfile, or None
        if the file cannot be read / parsed.
        """
        logger.info("Parsing BMS XML: %s", self.xml_path)

        try:
            tree = ET.parse(self.xml_path)
        except ET.ParseError as exc:
            logger.error("XML parse error in '%s': %s", self.xml_path, exc)
            return None
        except OSError as exc:
            logger.error("Cannot open '%s': %s", self.xml_path, exc)
            return None

        root = tree.getroot()  # <JoyAssgn>

        profile = DeviceProfile(
            name=self.name,
            source_file=self.xml_path,
        )

        # Parse each top-level section
        profile.axes = self._parse_axes(root)
        profile.povs = self._parse_povs(root)
        profile.buttons = self._parse_buttons(root)

        logger.info(
            "Device '%s': %d axes, %d POVs, %d buttons loaded.",
            self.name,
            len(profile.axes),
            len(profile.povs),
            len([b for b in profile.buttons if b.label]),
        )
        return profile

    # ------------------------------------------------------------------
    def _parse_axes(self, root: ET.Element) -> list[AxisAssignment]:
        """
        Parse the <axis> section.  Each <AxAssgn> child represents one
        physical axis.  We only include axes that have a non-empty AxisName.
        """
        assignments: list[AxisAssignment] = []
        axis_section = root.find("axis")
        if axis_section is None:
            logger.debug("No <axis> section found in %s.", self.xml_path.name)
            return assignments

        for idx, ax_elem in enumerate(axis_section.findall("AxAssgn")):
            axis_name_elem = ax_elem.find("AxisName")
            if axis_name_elem is None or not (axis_name_elem.text or "").strip():
                # Unassigned axis – skip
                continue

            axis_name = axis_name_elem.text.strip()

            # Invert flag
            invert_elem = ax_elem.find("Invert")
            invert = (invert_elem is not None and
                      (invert_elem.text or "").lower() == "true")

            # Optional saturation / deadzone (may be "None" string in BMS)
            sat_elem = ax_elem.find("Saturation")
            dz_elem = ax_elem.find("Deadzone")
            saturation = (sat_elem.text if sat_elem is not None
                          and sat_elem.text != "None" else None)
            deadzone = (dz_elem.text if dz_elem is not None
                        and dz_elem.text != "None" else None)

            # The axis_name IS the callback-style name in BMS (e.g.
            # "HUD_Brightness"). Use it directly as the human label after
            # substituting underscores with spaces.
            label = axis_name.replace("_", " ")

            assignments.append(AxisAssignment(
                axis_index=idx,
                axis_name=axis_name,
                label=label,
                invert=invert,
                saturation=saturation,
                deadzone=deadzone,
            ))

        return assignments

    # ------------------------------------------------------------------
    def _parse_povs(self, root: ET.Element) -> list[PovAssignment]:
        """
        Parse the <pov> section.
        Structure:
            <pov>
              <PovAssgn>              ← POV hat 0
                <direction>
                  <DirAssgn>         ← direction 0 (N)
                    <Callback>
                      <string>…</string>
                      <string>…</string>  ← shift-state variant
                    </Callback>
                  </DirAssgn>
                  …  (8 DirAssgn total, one per compass direction)
                </direction>
              </PovAssgn>
              …  (up to MAX_POV_HATS PovAssgn)
            </pov>

        We skip any direction where ALL callbacks are "SimDoNothing".
        """
        pov_list: list[PovAssignment] = []
        pov_section = root.find("pov")
        if pov_section is None:
            logger.debug("No <pov> section in %s.", self.xml_path.name)
            return pov_list

        for hat_idx, pov_elem in enumerate(pov_section.findall("PovAssgn")):
            if hat_idx >= MAX_POV_HATS:
                break  # BMS supports at most 4 hats

            pov_assignment = PovAssignment(pov_index=hat_idx)
            direction_section = pov_elem.find("direction")
            if direction_section is None:
                pov_list.append(pov_assignment)
                continue

            for dir_idx, dir_elem in enumerate(direction_section.findall("DirAssgn")):
                if dir_idx >= POV_DIRECTIONS:
                    break

                # Collect all <string> children inside <Callback>
                callback_elem = dir_elem.find("Callback")
                callbacks: list[str] = []
                if callback_elem is not None:
                    for str_elem in callback_elem.findall("string"):
                        cb = (str_elem.text or "").strip()
                        if cb and cb != "SimDoNothing":
                            callbacks.append(cb)

                if not callbacks:
                    # No active binding for this direction – skip
                    continue

                # Pick the most meaningful label from the available callbacks
                # (the first non-DoNothing one wins)
                primary_callback = callbacks[0]
                label = self.auto_key.get_label(primary_callback)

                pov_direction = PovDirection(
                    direction_index=dir_idx,
                    direction_label=POV_DIRECTION_LABELS.get(dir_idx, str(dir_idx)),
                    callbacks=callbacks,
                    label=label,
                )
                pov_assignment.directions.append(pov_direction)

            pov_list.append(pov_assignment)

        return pov_list

    # ------------------------------------------------------------------
    def _parse_buttons(self, root: ET.Element) -> list[ButtonAssignment]:
        """
        Parse the <dx> section.
        Structure:
            <dx>
              <DxAssgn>             ← DX button index 0 (BMS stores as 1)
                <assign>
                  <Assgn>           ← shift-state 0 (unshifted)
                    <Callback>SimICPCom1</Callback>
                    <Invoke>Default</Invoke>
                    <SoundID>122</SoundID>
                  </Assgn>
                  …  (up to 4 Assgn for different shift states)
                </assign>
              </DxAssgn>
              …  (up to 128 DxAssgn)
            </dx>

        BMS 4.38.1: the list position (0-based) is the true DX index.
        The displayed button number to users is (dx_index + BMS_DX_OFFSET).
        """
        buttons: list[ButtonAssignment] = []
        dx_section = root.find("dx")
        if dx_section is None:
            logger.debug("No <dx> section in %s.", self.xml_path.name)
            return buttons

        for btn_idx, dx_elem in enumerate(dx_section.findall("DxAssgn")):
            if btn_idx >= MAX_DX_BUTTONS:
                break

            assign_section = dx_elem.find("assign")
            callbacks: list[str] = []

            if assign_section is not None:
                for assgn_elem in assign_section.findall("Assgn"):
                    cb_elem = assgn_elem.find("Callback")
                    if cb_elem is not None:
                        cb = (cb_elem.text or "").strip()
                        if cb and cb != "SimDoNothing":
                            callbacks.append(cb)

            if not callbacks:
                # All bindings are SimDoNothing → unassigned button, skip
                continue

            # Use the FIRST non-DoNothing callback as the primary label source.
            # This represents the unshifted (default) binding which is most
            # relevant for a HOTAS diagram.
            primary_callback = callbacks[0]
            label = self.auto_key.get_label(primary_callback)

            # BMS user-visible button number = btn_idx + BMS_DX_OFFSET
            # but we store the zero-based index for Joystick-Diagrams.
            btn = ButtonAssignment(
                dx_index=btn_idx,
                callbacks=callbacks,
                label=label,
            )
            buttons.append(btn)

        return buttons


# ===========================================================================
#  MAIN PLUGIN CLASS
# ===========================================================================

class FalconBmsPlugin:
    """
    Joystick-Diagrams plugin for Falcon BMS 4.38+.

    Usage
    -----
    plugin = FalconBmsPlugin(config_directory=Path("C:/BMS/User/Config"))
    profiles = plugin.process()
    # profiles is a list of DeviceProfile objects ready for diagram rendering.

    Directory layout expected
    -------------------------
    <config_directory>/
        falconbms.key          (or auto.key – the master callback label file)
        Setup.v100.*.xml       (one XML per joystick device)
    """

    # Name of the key file inside the BMS Config directory.
    # BMS may name it "falconbms.key" or "auto.key" depending on version.
    KEY_FILENAMES: tuple[str, ...] = ("falconbms.key", "auto.key", "AUTO.KEY")

    def __init__(self, config_directory: Path | str):
        """
        Parameters
        ----------
        config_directory : Path or str
            Path to the BMS User/Config directory that contains both the
            key file and the Setup.v100.*.xml device files.
        """
        self.config_dir = Path(config_directory)
        self._auto_key_parser: Optional[AutoKeyParser] = None

    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Plugin display name."""
        return "Falcon BMS"

    @property
    def version(self) -> str:
        """Plugin version string."""
        return "1.0.0"

    @property
    def description(self) -> str:
        """Short description shown in Joystick-Diagrams UI."""
        return (
            "Parses Falcon BMS 4.38+ joystick XML configuration files "
            "(JoyAssgn) and AUTO.KEY to produce HOTAS device diagrams."
        )

    # ------------------------------------------------------------------
    def _find_key_file(self) -> Optional[Path]:
        """
        Search for the AUTO.KEY / falconbms.key file in the config directory.
        Returns the first match or None if not found.
        """
        for filename in self.KEY_FILENAMES:
            candidate = self.config_dir / filename
            if candidate.exists():
                logger.info("Found key file: %s", candidate)
                return candidate
        logger.warning(
            "No key file found in '%s'. Searched for: %s",
            self.config_dir,
            ", ".join(self.KEY_FILENAMES),
        )
        return None

    # ------------------------------------------------------------------
    def _find_xml_files(self) -> list[Path]:
        """
        Enumerate all BMS joystick XML files in the config directory.
        They match the pattern: Setup.v<digits>.*.xml
        """
        pattern = "Setup.v*.xml"
        xml_files = sorted(self.config_dir.glob(pattern))
        logger.info("Found %d device XML files in '%s'.", len(xml_files), self.config_dir)
        return xml_files

    # ------------------------------------------------------------------
    def process(self) -> list[DeviceProfile]:
        """
        Entry point called by Joystick-Diagrams.

        Returns a list of DeviceProfile objects – one per physical device –
        populated with axis, POV and button label data ready for diagram
        rendering.
        """
        logger.info("=== Falcon BMS Plugin: starting processing ===")

        # 1. Locate and parse the AUTO.KEY label file
        key_file = self._find_key_file()
        # AutoKeyParser handles a None path gracefully (logs a warning)
        self._auto_key_parser = AutoKeyParser(key_file or Path("nonexistent.key"))

        # 2. Enumerate device XML files
        xml_files = self._find_xml_files()
        if not xml_files:
            logger.warning(
                "No Setup.v*.xml files found in '%s'. "
                "Ensure the BMS User/Config directory is correct.",
                self.config_dir,
            )
            return []

        # 3. Parse each device XML
        profiles: list[DeviceProfile] = []
        for xml_path in xml_files:
            parser = BmsXmlParser(xml_path, self._auto_key_parser)
            profile = parser.parse()
            if profile is not None:
                profiles.append(profile)

        logger.info(
            "=== Falcon BMS Plugin: processed %d device profiles ===",
            len(profiles),
        )
        return profiles
    
    def parse(self) -> ProfileCollection:
        """
        Alias for process() to conform to PluginInterface expectations.
        """
        profiles = self.process()
        print(f"Falcon BMS Plugin: Parsed {len(profiles)} device profiles.")
        col = ProfileCollection()
        prof = col.create_profile("BMS")
        prof.devices = {p.name: p for p in profiles}
        return col


# ===========================================================================
#  OUTPUT FORMATTER  (mirrors the Joystick-Diagrams expected data shape)
# ===========================================================================

def format_profiles_for_joystick_diagrams(
    profiles: list[DeviceProfile],
) -> dict[str, dict]:
    """
    Convert DeviceProfile objects into the dictionary structure that
    Joystick-Diagrams' diagram renderer consumes.

    Output structure
    ----------------
    {
        "<DeviceName>": {
            "axes": {
                <axis_index>: {
                    "name":  "<AxisName>",
                    "label": "<Human Label>",
                    "invert": bool,
                },
                …
            },
            "povs": {
                <pov_index>: {
                    "<N|NE|E|…>": "<Human Label>",
                    …
                },
                …
            },
            "buttons": {
                <dx_index>: "<Human Label>",
                …
            },
        },
        …
    }
    """
    output: dict[str, dict] = {}

    for profile in profiles:
        device_data: dict[str, dict] = {
            "axes": {},
            "povs": {},
            "buttons": {},
        }

        # ---- Axes -------------------------------------------------------
        for axis in profile.axes:
            device_data["axes"][axis.axis_index] = {
                "name": axis.axis_name,
                "label": axis.label,
                "invert": axis.invert,
                "saturation": axis.saturation,
                "deadzone": axis.deadzone,
            }

        # ---- POVs -------------------------------------------------------
        for pov in profile.povs:
            pov_data: dict[str, str] = {}
            for direction in pov.directions:
                if direction.label:
                    pov_data[direction.direction_label] = direction.label
            if pov_data:  # Only include POVs that have at least one binding
                device_data["povs"][pov.pov_index] = pov_data

        # ---- Buttons ----------------------------------------------------
        for btn in profile.buttons:
            if btn.label:
                # Key is the user-visible BMS button number (1-based)
                user_btn_number = btn.dx_index + BMS_DX_OFFSET
                device_data["buttons"][user_btn_number] = btn.label

        output[profile.name] = device_data

    return output


# ===========================================================================
#  COMMAND-LINE ENTRY POINT (for standalone testing)
# ===========================================================================

def main() -> None:
    """
    Standalone CLI entry point for testing the plugin outside of
    the Joystick-Diagrams application.

    Usage:
        python falcon_bms.py <BMS_CONFIG_DIRECTORY>

    Example:
        python falcon_bms.py "C:/Falcon BMS 4.38/User/Config"
    """
    import sys
    import json

    # Configure logging to stdout for CLI use
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python falcon_bms.py <BMS_CONFIG_DIRECTORY>")
        print("\nThis plugin parses Falcon BMS joystick XML files and AUTO.KEY")
        print("from the specified User/Config directory.")
        sys.exit(1)

    config_dir = Path(sys.argv[1])
    if not config_dir.is_dir():
        print(f"ERROR: Directory not found: {config_dir}")
        sys.exit(1)

    # Run the plugin
    plugin = FalconBmsPlugin(config_directory=config_dir)
    profiles = plugin.process()

    if not profiles:
        print("No device profiles found. Check the config directory and log output.")
        sys.exit(1)

    # Format and pretty-print the output
    output = format_profiles_for_joystick_diagrams(profiles)
    print("\n=== Falcon BMS Plugin Output ===\n")
    print(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"\nTotal devices processed: {len(output)}")
    for name, data in output.items():
        btn_count = len(data["buttons"])
        axis_count = len(data["axes"])
        pov_count = sum(len(dirs) for dirs in data["povs"].values())
        print(
            f"  {name}: "
            f"{btn_count} buttons, {axis_count} axes, {pov_count} POV directions"
        )


if __name__ == "__main__":
    main()

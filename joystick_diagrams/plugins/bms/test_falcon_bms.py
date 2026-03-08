"""
================================================================================
Test Suite for Falcon BMS Joystick-Diagrams Plugin
================================================================================
Tests cover:
  - AUTO.KEY parsing (keyboard and joystick lines, comments, SimDoNothing skip)
  - Callback name cleaning (prefix stripping, CamelCase spacing)
  - Device name extraction from XML filename
  - XML parsing (axes, POVs, buttons, DX offset)
  - Full integration test using synthetic XML + KEY content
  - Output formatter
================================================================================
"""

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Import the plugin module.  Adjust the import path if this test file is run
# from a different working directory.
# ---------------------------------------------------------------------------
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from falcon_bms import (
    AutoKeyParser,
    BmsXmlParser,
    DeviceProfile,
    FalconBmsPlugin,
    clean_callback_name,
    extract_device_name,
    format_profiles_for_joystick_diagrams,
    BMS_DX_OFFSET,
)


# ===========================================================================
#  HELPERS
# ===========================================================================

def write_temp_file(directory: str, filename: str, content: str) -> Path:
    """Write content to a temp file and return its Path."""
    path = Path(directory) / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ===========================================================================
#  UNIT TESTS: clean_callback_name
# ===========================================================================

class TestCleanCallbackName(unittest.TestCase):

    def test_sim_prefix_stripped(self):
        self.assertEqual(clean_callback_name("SimTMSUp"), "TMS Up")

    def test_otw_prefix_stripped(self):
        self.assertEqual(clean_callback_name("OTWViewLeft"), "View Left")

    def test_af_prefix_stripped(self):
        self.assertEqual(clean_callback_name("AFGearDown"), "Gear Down")

    def test_sim_do_nothing_returns_empty(self):
        self.assertEqual(clean_callback_name("SimDoNothing"), "")

    def test_icp_retained(self):
        result = clean_callback_name("SimICPCom1")
        # Should contain ICP and Com
        self.assertIn("ICP", result)
        self.assertIn("Com", result)

    def test_camel_case_spacing(self):
        self.assertEqual(clean_callback_name("AFGearUp"), "Gear Up")

    def test_no_prefix(self):
        # If callback has no known prefix, it should still be spaced
        result = clean_callback_name("RecenterJoystick")
        # RecenterJoystick → "Recenter" prefix stripped → "Joystick"
        self.assertIn("Joystick", result)

    def test_set_right_throttle(self):
        result = clean_callback_name("SetRightThrottleIdleCutOffDetent")
        # "SetRightThrottle" prefix stripped → "IdleCutOffDetent" → spaced
        self.assertNotIn("SetRight", result)

    def test_already_clean(self):
        # A name with no prefix and no CamelCase
        result = clean_callback_name("ABCDEF")
        self.assertIsInstance(result, str)


# ===========================================================================
#  UNIT TESTS: extract_device_name
# ===========================================================================

class TestExtractDeviceName(unittest.TestCase):

    def test_icp_device(self):
        filename = "Setup.v100.Simgears ICP LT IT {CC9D52E0-1A6B-11EF-8001-444553540000}.xml"
        result = extract_device_name(filename)
        self.assertIn("ICP", result)

    def test_mfd1_device(self):
        filename = "Setup.v100.F16 MFD 1 {36EE15C0-19E6-11EF-8003-444553540000}.xml"
        result = extract_device_name(filename)
        # Should truncate to "MFD_1" or contain MFD
        self.assertIn("MFD", result)

    def test_joystick_truncation(self):
        filename = "Setup.v100.Thrustmaster T16000M Joystick {ABCD1234-0000-0000-0000-000000000000}.xml"
        result = extract_device_name(filename)
        self.assertEqual(result, "Joystick")

    def test_throttle_truncation(self):
        # "WINWING Throttle Base" → truncated to "Throttle Base"
        # (the name is trimmed to start at the "Throttle" keyword and retain
        #  any suffix that is part of the device's own name)
        filename = "Setup.v100.WINWING Throttle Base {ABCD0000-0000-0000-0000-000000000000}.xml"
        result = extract_device_name(filename)
        self.assertTrue(result.startswith("Throttle"),
                        f"Expected result to start with 'Throttle', got '{result}'")

    def test_no_known_short_label(self):
        filename = "Setup.v100.Custom Device XL {00000000-0000-0000-0000-000000000001}.xml"
        result = extract_device_name(filename)
        self.assertEqual(result, "Custom Device XL")

    def test_malformed_filename(self):
        # Should not raise, just return something sensible
        result = extract_device_name("notasetupfile.xml")
        self.assertIsInstance(result, str)


# ===========================================================================
#  UNIT TESTS: AutoKeyParser
# ===========================================================================

AUTO_KEY_SAMPLE = """
# Falcon BMS AUTO.KEY sample

FlightEchelonRight -1 0 0XFFFFFFFF 0 0 0 1 "FLIGHT: Go Echolon Left"
FlightEchelonLeft -1 0 0XFFFFFFFF 0 0 0 1 "FLIGHT: Go Echolon Right"
SimDoNothing -1 0 0XFFFFFFFF 0 0 0 -1 "======== 8.08 CREW CHIEF ========"
SimRemoveEpuPin -1 0 0XFFFFFFFF 0 0 0 1 "CHIEF: Remove EPU Safety Pin"

#======== Simgears ICP LT IT ========
SimICPCom1 256 -1 -2 0 0x0 122
SimICPCom2 257 -1 -2 0 0x0 122

#======== WINCTRL Orion Joystick Base Metal 2  JGRIP-F16 ========
SimTMSUp 159 -1 -2 0 0x0 -1
SimTMSDown 161 -1 -2 0 0x0 -1
AFGearUp 456 -1 -2 0 0x0 119
"""


class TestAutoKeyParser(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.key_path = write_temp_file(self.tmp.name, "auto.key", AUTO_KEY_SAMPLE)
        self.parser = AutoKeyParser(self.key_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_keyboard_line_description_parsed(self):
        # "CHIEF: Remove EPU Safety Pin" → after colon: "Remove EPU Safety Pin"
        label = self.parser.get_label("SimRemoveEpuPin")
        self.assertEqual(label, "Remove EPU Safety Pin")

    def test_keyboard_line_flight(self):
        # "FLIGHT: Go Echolon Left" → "Go Echolon Left"
        label = self.parser.get_label("FlightEchelonRight")
        self.assertEqual(label, "Go Echolon Left")

    def test_sim_do_nothing_not_in_labels(self):
        # SimDoNothing lines should be skipped
        self.assertNotIn("SimDoNothing", self.parser.callback_labels)

    def test_joystick_line_callback_cleaned(self):
        # SimTMSUp has no description → cleaned callback
        label = self.parser.get_label("SimTMSUp")
        self.assertIn("TMS", label)
        self.assertIn("Up", label)

    def test_unknown_callback_falls_back(self):
        # Callback not in file → falls back to clean_callback_name
        label = self.parser.get_label("SimSomeUnknownFunc")
        self.assertIsInstance(label, str)
        self.assertGreater(len(label), 0)

    def test_missing_key_file(self):
        # Should not raise, just log a warning
        parser = AutoKeyParser(Path("/nonexistent/path/auto.key"))
        label = parser.get_label("SimTMSUp")
        self.assertIsInstance(label, str)


# ===========================================================================
#  UNIT TESTS: BmsXmlParser
# ===========================================================================

SAMPLE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<JoyAssgn xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <detentPosition>
    <AB>65536</AB>
    <IDLE>0</IDLE>
  </detentPosition>
  <axis>
    <AxAssgn>
      <AxisName />
      <AssgnDate>1998-12-12T12:00:00</AssgnDate>
      <Invert>false</Invert>
      <Saturation>None</Saturation>
      <Deadzone>None</Deadzone>
    </AxAssgn>
    <AxAssgn>
      <AxisName>HUD_Brightness</AxisName>
      <AssgnDate>2025-09-23T23:33:13</AssgnDate>
      <Invert>false</Invert>
      <Saturation>None</Saturation>
      <Deadzone>None</Deadzone>
    </AxAssgn>
    <AxAssgn>
      <AxisName>FLIR_Brightness</AxisName>
      <AssgnDate>2024-06-23T23:52:58</AssgnDate>
      <Invert>true</Invert>
      <Saturation>0.9</Saturation>
      <Deadzone>0.05</Deadzone>
    </AxAssgn>
  </axis>
  <pov>
    <PovAssgn>
      <direction>
        <DirAssgn>
          <Callback>
            <string>AFElevatorTrimUp</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
        <DirAssgn>
          <Callback>
            <string>SimDoNothing</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
        <DirAssgn>
          <Callback>
            <string>AFAileronTrimRight</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
        <DirAssgn>
          <Callback>
            <string>SimDoNothing</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
        <DirAssgn>
          <Callback>
            <string>AFElevatorTrimDown</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
        <DirAssgn>
          <Callback>
            <string>SimDoNothing</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
        <DirAssgn>
          <Callback>
            <string>AFAileronTrimLeft</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
        <DirAssgn>
          <Callback>
            <string>SimDoNothing</string>
            <string>SimDoNothing</string>
          </Callback>
          <SoundID><int>0</int><int>0</int></SoundID>
        </DirAssgn>
      </direction>
    </PovAssgn>
  </pov>
  <dx>
    <DxAssgn>
      <assign>
        <Assgn>
          <Callback>SimICPCom1</Callback>
          <Invoke>Default</Invoke>
          <SoundID>122</SoundID>
        </Assgn>
        <Assgn>
          <Callback>SimDoNothing</Callback>
          <Invoke>Default</Invoke>
          <SoundID>0</SoundID>
        </Assgn>
      </assign>
    </DxAssgn>
    <DxAssgn>
      <assign>
        <Assgn>
          <Callback>SimDoNothing</Callback>
          <Invoke>Default</Invoke>
          <SoundID>0</SoundID>
        </Assgn>
      </assign>
    </DxAssgn>
    <DxAssgn>
      <assign>
        <Assgn>
          <Callback>SimICPIFF</Callback>
          <Invoke>Default</Invoke>
          <SoundID>122</SoundID>
        </Assgn>
      </assign>
    </DxAssgn>
  </dx>
</JoyAssgn>
"""


class TestBmsXmlParser(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()

        # Write key file
        self.key_path = write_temp_file(self.tmp.name, "auto.key", AUTO_KEY_SAMPLE)
        self.auto_key = AutoKeyParser(self.key_path)

        # Write XML file with a BMS-style name
        self.xml_filename = (
            "Setup.v100.Simgears ICP LT IT "
            "{CC9D52E0-1A6B-11EF-8001-444553540000}.xml"
        )
        self.xml_path = write_temp_file(self.tmp.name, self.xml_filename, SAMPLE_XML)
        self.parser = BmsXmlParser(self.xml_path, self.auto_key)

    def tearDown(self):
        self.tmp.cleanup()

    def test_device_name_extracted(self):
        self.assertIn("ICP", self.parser.device_name)

    def test_axes_parsed(self):
        profile = self.parser.parse()
        self.assertIsNotNone(profile)
        # Only 2 axes should be extracted (the empty AxisName is skipped)
        self.assertEqual(len(profile.axes), 2)

    def test_axis_labels(self):
        profile = self.parser.parse()
        labels = [a.label for a in profile.axes]
        self.assertIn("HUD Brightness", labels)
        self.assertIn("FLIR Brightness", labels)

    def test_axis_invert_and_extras(self):
        profile = self.parser.parse()
        flir = next(a for a in profile.axes if "FLIR" in a.label)
        self.assertTrue(flir.invert)
        self.assertEqual(flir.saturation, "0.9")
        self.assertEqual(flir.deadzone, "0.05")

    def test_pov_parsed(self):
        profile = self.parser.parse()
        # Should have 1 POV with 4 active directions (N, E, S, W)
        self.assertEqual(len(profile.povs), 1)
        active_dirs = profile.povs[0].directions
        self.assertEqual(len(active_dirs), 4)

    def test_pov_direction_labels(self):
        profile = self.parser.parse()
        dir_labels = [d.direction_label for d in profile.povs[0].directions]
        self.assertIn("N", dir_labels)   # index 0
        self.assertIn("E", dir_labels)   # index 2
        self.assertIn("S", dir_labels)   # index 4
        self.assertIn("W", dir_labels)   # index 6

    def test_buttons_parsed(self):
        profile = self.parser.parse()
        # DxAssgn[0] = SimICPCom1 (assigned)
        # DxAssgn[1] = SimDoNothing (skipped)
        # DxAssgn[2] = SimICPIFF (assigned)
        self.assertEqual(len(profile.buttons), 2)

    def test_button_dx_index(self):
        profile = self.parser.parse()
        indices = [b.dx_index for b in profile.buttons]
        # DxAssgn positions 0 and 2
        self.assertIn(0, indices)
        self.assertIn(2, indices)

    def test_button_label_not_empty(self):
        profile = self.parser.parse()
        for btn in profile.buttons:
            self.assertGreater(len(btn.label), 0, f"Empty label for dx_index={btn.dx_index}")

    def test_malformed_xml_returns_none(self):
        bad_xml_path = write_temp_file(self.tmp.name, "bad.xml", "<not valid xml")
        parser = BmsXmlParser(bad_xml_path, self.auto_key)
        profile = parser.parse()
        self.assertIsNone(profile)


# ===========================================================================
#  UNIT TESTS: format_profiles_for_joystick_diagrams
# ===========================================================================

class TestFormatter(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.key_path = write_temp_file(self.tmp.name, "auto.key", AUTO_KEY_SAMPLE)
        auto_key = AutoKeyParser(self.key_path)
        xml_filename = (
            "Setup.v100.Simgears ICP LT IT "
            "{CC9D52E0-1A6B-11EF-8001-444553540000}.xml"
        )
        xml_path = write_temp_file(self.tmp.name, xml_filename, SAMPLE_XML)
        parser = BmsXmlParser(xml_path, auto_key)
        self.profile = parser.parse()

    def tearDown(self):
        self.tmp.cleanup()

    def test_output_is_dict(self):
        output = format_profiles_for_joystick_diagrams([self.profile])
        self.assertIsInstance(output, dict)

    def test_device_name_is_key(self):
        output = format_profiles_for_joystick_diagrams([self.profile])
        self.assertIn(self.profile.device_name, output)

    def test_sections_present(self):
        output = format_profiles_for_joystick_diagrams([self.profile])
        device_data = output[self.profile.device_name]
        self.assertIn("axes", device_data)
        self.assertIn("povs", device_data)
        self.assertIn("buttons", device_data)

    def test_button_keys_are_1_based(self):
        """Button keys in output should be 1-based (DX index + BMS_DX_OFFSET)."""
        output = format_profiles_for_joystick_diagrams([self.profile])
        buttons = output[self.profile.device_name]["buttons"]
        # dx_index=0 → key=1, dx_index=2 → key=3
        self.assertIn(1, buttons)
        self.assertIn(3, buttons)

    def test_axis_structure(self):
        output = format_profiles_for_joystick_diagrams([self.profile])
        axes = output[self.profile.device_name]["axes"]
        for idx, ax_data in axes.items():
            self.assertIn("name", ax_data)
            self.assertIn("label", ax_data)
            self.assertIn("invert", ax_data)


# ===========================================================================
#  INTEGRATION TEST: FalconBmsPlugin end-to-end
# ===========================================================================

class TestFalconBmsPluginIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()

        # Write a key file
        write_temp_file(self.tmp.name, "auto.key", AUTO_KEY_SAMPLE)

        # Write an XML device file
        xml_filename = (
            "Setup.v100.Simgears ICP LT IT "
            "{CC9D52E0-1A6B-11EF-8001-444553540000}.xml"
        )
        write_temp_file(self.tmp.name, xml_filename, SAMPLE_XML)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plugin_processes_files(self):
        plugin = FalconBmsPlugin(config_directory=self.tmp.name)
        profiles = plugin.process()
        self.assertGreater(len(profiles), 0)

    def test_plugin_returns_device_profiles(self):
        plugin = FalconBmsPlugin(config_directory=self.tmp.name)
        profiles = plugin.process()
        for p in profiles:
            self.assertIsInstance(p, DeviceProfile)

    def test_plugin_empty_directory(self):
        """Plugin should return empty list (not crash) if no XML files found."""
        with TemporaryDirectory() as empty_dir:
            plugin = FalconBmsPlugin(config_directory=empty_dir)
            profiles = plugin.process()
            self.assertEqual(profiles, [])

    def test_plugin_metadata(self):
        plugin = FalconBmsPlugin(config_directory=self.tmp.name)
        self.assertEqual(plugin.name, "Falcon BMS")
        self.assertIsInstance(plugin.version, str)
        self.assertIsInstance(plugin.description, str)


# ===========================================================================
#  MAIN
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)

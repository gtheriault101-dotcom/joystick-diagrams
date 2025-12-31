import tempfile
from pathlib import Path

from joystick_diagrams.plugins.falconbms.falconbms_parser import FalconBMSParser


def make_sample_xml(path: Path):
    # Minimal structure with dx, axis, pov sections
    xml = """<?xml version="1.0" encoding="utf-8"?>
<JoyAssgn>
  <dx>
    <DxAssgn>
      <name>Fire Gun</name>
      <button>1</button>
    </DxAssgn>
    <DxAssgn>
      <name>CM Release</name>
      <button>2</button>
    </DxAssgn>
  </dx>
  <axis>
    <AxAssgn>
      <name>Throttle</name>
      <axis>SLIDER1</axis>
    </AxAssgn>
    <AxAssgn>
      <name>Roll</name>
      <axis>X</axis>
    </AxAssgn>
  </axis>
  <pov>
    <PovAssgn>
      <name>Hat Up</name>
      <U>100</U>
    </PovAssgn>
  </pov>
</JoyAssgn>
"""
    path.write_text(xml, encoding="utf-8")


def test_falconbms_parser_minimal():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        f = td_path.joinpath("sample.xml")
        make_sample_xml(f)

        parser = FalconBMSParser(f)
        profiles = parser.process_profiles()

        # Expect one profile keyed by filename stem
        assert len(profiles) == 1
        key = list(profiles.profiles.keys())[0]
        profile = profiles.profiles[key]
        # Device should exist
        assert profile.get_devices() is not None
        # Flattened inputs should include buttons/axis/hats
        devices = profile.get_devices()
        assert len(devices) == 1

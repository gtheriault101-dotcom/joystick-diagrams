"""Falcon BMS XML parser for Joystick Diagrams

Parses Falcon BMS Setup XML files extracting DX codes, axis and POV
assignments and converts them into the library ProfileCollection format.
"""
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
import uuid

from joystick_diagrams.input.profile_collection import ProfileCollection
from joystick_diagrams.input.profile import Profile_
from joystick_diagrams.input.device import Device_
from joystick_diagrams.input.button import Button
from joystick_diagrams.input.axis import Axis, AxisDirection, AxisSlider
from joystick_diagrams.input.hat import Hat, HatDirection

_logger = logging.getLogger(__name__)


class FalconBMSParser:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def process_profiles(self) -> ProfileCollection:
        collection = ProfileCollection()

        files = []
        if self.path.is_file() and self.path.suffix.lower() == ".xml":
            files = [self.path]
        elif self.path.is_dir():
            files = list(self.path.glob("*.xml"))
        else:
            raise FileNotFoundError(f"FalconBMS: Path {self.path} not found")

        for f in files:
            name = f.stem
            profile_obj = collection.create_profile(profile_name=name)

            # Create a device with a generated UUID for this file
            guid = str(uuid.uuid4())
            device = profile_obj.add_device(guid, name)

            try:
                tree = ET.parse(f)
                root = tree.getroot()
            except ET.ParseError as e:
                _logger.error(f"Failed to parse {f}: {e}")
                continue

            # Parse DX assignments (search recursively for ids and names)
            dx = root.find("dx")
            if dx is not None:
                for dxassgn in dx.findall("DxAssgn"):
                    button_id = None
                    operation = None

                    # Walk all child elements and attributes for useful data
                    texts = []
                    for el in dxassgn.iter():
                        if el is dxassgn:
                            continue
                        text = (el.text or "").strip()
                        tag = (el.tag or "").lower()
                        texts.append(text)

                        # operation candidates
                        if any(k in tag for k in ("name", "desc", "function", "operation", "cmd")):
                            if text:
                                operation = operation or text

                        # numeric id anywhere
                        if button_id is None:
                            # direct digits
                            if text.isdigit():
                                button_id = int(text)
                                continue
                            # attributes
                            for _, v in el.items():
                                if v.isdigit():
                                    button_id = int(v)
                                    break

                    # final fallback: scan stringified subelements for integers
                    if button_id is None:
                        import re

                        all_text = " ".join(texts)
                        m = re.search(r"\b(\d{1,4})\b", all_text)
                        if m:
                            button_id = int(m.group(1))

                    if button_id is not None:
                        if operation is None:
                            # select first meaningful text
                            operation = self._first_meaningful_text(texts)

                        # sanitize operation text
                        operation = self._sanitize_operation(operation)

                        try:
                            device.create_input(Button(button_id), operation)
                        except Exception:
                            _logger.debug(f"Could not create Button for id {button_id}")

            # Parse axis assignments
            axis = root.find("axis")
            if axis is not None:
                for ax in axis.findall("AxAssgn"):
                    axis_id = None
                    operation = None

                    for el in ax.iter():
                        if el is ax:
                            continue
                        text = (el.text or "").strip()
                        tag = (el.tag or "").lower()

                        if any(k in tag for k in ("name", "desc", "function", "operation", "cmd")) and text:
                            operation = operation or text

                        # slider token
                        if axis_id is None and "slider" in text.lower():
                            import re

                            m = re.search(r"slider\s*[:_\s]?(\d+)", text, flags=re.IGNORECASE)
                            if m:
                                axis_id = int(m.group(1))
                                continue

                        # axis letter
                        if axis_id is None and text.upper() in AxisDirection.__members__:
                            axis_id = text.upper()
                            continue

                        # numeric axis id
                        if axis_id is None and text.isdigit():
                            axis_id = int(text)

                    # fallback search
                    if axis_id is None:
                        combined = " ".join((e.text or "") for e in ax.iter())
                        for name in AxisDirection.__members__:
                            if name in combined.upper():
                                axis_id = name
                                break

                    if axis_id is not None:
                        try:
                            operation = self._first_meaningful_text([ (e.text or "").strip() for e in ax.iter() ]) if operation is None else operation
                            operation = self._sanitize_operation(operation)
                            if isinstance(axis_id, int):
                                device.create_input(AxisSlider(axis_id), operation or "")
                            else:
                                device.create_input(Axis(AxisDirection[axis_id]), operation or "")
                        except Exception:
                            _logger.debug(f"Could not create Axis for {axis_id}")

            # Parse POV / hats
            pov = root.find("pov")
            if pov is not None:
                for i, povassgn in enumerate(pov.findall("PovAssgn"), start=1):
                    operation = None
                    # try to extract operation and direction tags
                    texts = [ (e.text or "").strip() for e in povassgn.iter() if e is not povassgn ]
                    for el in povassgn.iter():
                        if el is povassgn:
                            continue
                        tag = (el.tag or "").upper()
                        text = (el.text or "").strip()
                        if any(k in tag.lower() for k in ("name", "desc", "function", "operation", "cmd")) and text:
                            operation = operation or text

                        if tag in HatDirection.__members__:
                            try:
                                op = self._sanitize_operation(operation or self._first_meaningful_text(texts))
                                device.create_input(Hat(i, HatDirection[tag]), op or "")
                            except Exception:
                                _logger.debug(f"Could not create Hat for {tag}")

                    # fallback: search text for direction tokens
                    if operation is None:
                        combined = " ".join(texts)
                        for dir_tag in HatDirection.__members__:
                            if dir_tag in combined.upper():
                                try:
                                    device.create_input(Hat(i, HatDirection[dir_tag]), self._sanitize_operation(combined))
                                except Exception:
                                    _logger.debug(f"Could not create Hat for {dir_tag}")
                                break

        return collection

    def _first_meaningful_text(self, texts: list[str]) -> str | None:
        """Return the first non-empty, non-ignored text from a list."""
        ignore = {"", "0", "simdonothing", "assign=", "none"}
        for t in texts:
            if not t:
                continue
            tt = t.strip()
            if not tt:
                continue
            if tt.lower() in ignore:
                continue
            # skip pure numbers
            if tt.isdigit():
                continue
            return tt
        return None

    def _sanitize_operation(self, op: str | None) -> str:
        if not op:
            return ""
        # remove common prefixes and collapse whitespace
        s = op.replace("assign=", "").strip()
        import re

        s = re.sub(r"\s+", " ", s)
        # strip surrounding punctuation
        s = s.strip(" \n\t\r\"',;:")
        # if it's just SimDoNothing or similar, return empty
        if s.lower().startswith("simdonothing"):
            return ""
        return s

        


if __name__ == "__main__":
    import sys
    p = FalconBMSParser(sys.argv[1])
    profiles = p.process_profiles()
    print(profiles.profiles.keys())

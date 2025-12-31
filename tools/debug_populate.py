from pathlib import Path
from joystick_diagrams.plugins.falconbms.falconbms_parser import FalconBMSParser
from joystick_diagrams.template import Template
from joystick_diagrams.export_device import ExportDevice
from joystick_diagrams.input.profile_collection import ProfileCollection

from joystick_diagrams.input.button import Button

from joystick_diagrams.input.modifier import Modifier
from joystick_diagrams.input.axis import Axis, AxisDirection
from joystick_diagrams.input.hat import Hat, HatDirection

from joystick_diagrams.export import sanitize_string_for_svg

xml_path = Path(r'G:\Falcon BMS 4.38\User\Config\Setup.v100.F16 MFD 1 {36EE15C0-19E6-11EF-8003-444553540000}.xml')
template_path = Path(r'C:\Users\theri\projects\joystick-diagrams\templates\WinWing\Guy\throttle.svg')

p = FalconBMSParser(xml_path)
profiles = p.process_profiles()
prof = list(profiles.profiles.values())[0]
dev = list(prof.get_devices().values())[0]

class MockWrapper:
    def __init__(self, name):
        self.profile_name = name

pw = MockWrapper(prof.name)
templ = Template(template_path)
export_dev = ExportDevice(device=dev, _template=templ, profile_wrapper=pw)

tpl = templ
modified_template_data = tpl.raw_data

def map_identifier_to_template(identifier: str):
    import re
    key = identifier.lower()
    buttons = {b.lower() for b in tpl.get_template_buttons()}
    axes = {a.lower() for a in tpl.get_template_axis()}
    hats = {h.lower() for h in tpl.get_template_hats()}
    if key in buttons or key in axes or key in hats:
        return identifier
    parts = identifier.split("_")
    if parts[0].upper() == "BUTTON" and len(parts) >= 2:
        try:
            n = int(parts[1])
        except Exception:
            return None
        max_btn = 0
        for b in buttons:
            m = re.search(r"(\d+)$", b)
            if m:
                max_btn = max(max_btn, int(m.group(1)))
        if max_btn > 0:
            while n > max_btn:
                n -= 100
            if n <= 0:
                n = 1
            candidate = f"button_{n}"
            if candidate in buttons:
                return f"BUTTON_{n}"
    if parts[0].upper() == "POV" and len(parts) >= 3:
        pov_id = parts[1]
        for h in hats:
            if h.startswith(f"pov_{pov_id}_"):
                return h.upper()
    return None

for input_key, input_object in export_dev.device.get_combined_inputs().items():
    mapped_key = map_identifier_to_template(input_key) or map_identifier_to_template(input_key.upper())
    tried_keys = [input_key]
    if mapped_key and mapped_key not in tried_keys:
        tried_keys.append(mapped_key)

    print('\nProcessing', input_key, 'command=', repr(input_object.command), 'mapped=', mapped_key)
    for tk in tried_keys:
        before = modified_template_data
        modified_template_data = modified_template_data.replace(tk, sanitize_string_for_svg(input_object.command))
        if modified_template_data != before:
            print('Replaced', tk)
            break
        else:
            print('Did not replace', tk)

print('\nFinal snippet around button_15:')
txt = modified_template_data
idx = txt.lower().find('button_15')
if idx!=-1:
    print(txt[max(0,idx-80):idx+200])
else:
    print('button_15 not in modified template')

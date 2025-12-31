from pathlib import Path
from joystick_diagrams.plugins.falconbms.falconbms_parser import FalconBMSParser
from joystick_diagrams.template import Template
from joystick_diagrams.export_device import ExportDevice
from joystick_diagrams.export import populate_template

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

result = populate_template(export_dev)
print('Has SimHUDVelocity?', 'SimHUDVelocity' in result)
print('Has SimRadarGainDown?', 'SimRadarGainDown' in result)
print('Has Default?', 'Default' in result)
print('Snippet around Button_15:')
idx = result.find('Button_15')
if idx!=-1:
    print(result[max(0,idx-80):idx+200])
else:
    print('Button_15 not found')

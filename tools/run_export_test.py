from pathlib import Path
from joystick_diagrams.plugins.falconbms.falconbms_parser import FalconBMSParser
from joystick_diagrams.template import Template
from joystick_diagrams.export import export_device_to_templates
from joystick_diagrams.export_device import ExportDevice


def main():
    xml_path = Path(r'G:\Falcon BMS 4.38\User\Config\Setup.v100.F16 MFD 1 {36EE15C0-19E6-11EF-8003-444553540000}.xml')
    template_path = Path(r'C:\Users\theri\projects\joystick-diagrams\templates\WinWing\Guy\throttle.svg')
    output_dir = Path(r'C:\Users\theri\projects\joystick-diagrams\output_test')
    output_dir.mkdir(parents=True, exist_ok=True)

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

    export_device_to_templates(export_dev, output_dir)

    out_files = list(output_dir.glob('*.svg'))
    print('Saved files:', out_files)
    if out_files:
        txt = out_files[0].read_text(encoding='utf-8')
        for i, line in enumerate(txt.splitlines(), 1):
            if any(k in line for k in ['BUTTON_', 'AXIS_', 'POV_', 'TEMPLATE_NAME', 'CURRENT_DATE']):
                print(i, line)


if __name__ == '__main__':
    main()

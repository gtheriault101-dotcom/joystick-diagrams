from pathlib import Path
from joystick_diagrams.plugins.falconbms.main import ParserPlugin

p = ParserPlugin()
# point to your FalconBMS XML file or folder:
p.set_path(Path(r"G:\Falcon BMS 4.38\User\Config\Setup.v100.F16 MFD 1 {36EE15C0-19E6-11EF-8003-444553540000}.xml"))
# export into C:\temp (creates falconbms_mappings.json there)
p.export_mappings(Path(r".\temp\falconbms_mappings.json"))
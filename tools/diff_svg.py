from pathlib import Path
from joystick_diagrams.template import Template

template_path = Path(r'C:\Users\theri\projects\joystick-diagrams\templates\WinWing\Guy\throttle.svg')
out_path = Path(r'C:\Users\theri\projects\joystick-diagrams\output_test')
out_files = list(out_path.glob('*.svg'))
if not out_files:
    print('No output files')
    raise SystemExit(1)

out_file = out_files[0]

tpl = Template(template_path)
tpl_txt = tpl.raw_data
out_txt = out_file.read_text(encoding='utf-8')

keys = sorted(list(tpl.get_template_buttons()) + list(tpl.get_template_axis()) + list(tpl.get_template_hats()))
print('Template placeholders count:', len(keys))
for k in keys[:50]:
    if k.lower() not in out_txt.lower():
        print('MISSING in output:', k)
    else:
        print('FOUND in output:', k)

print('\nSample of output around first BUTTON_')
idx = out_txt.lower().find('button_')
if idx!=-1:
    print(out_txt[max(0,idx-80):idx+200])
else:
    print('no button_ in output')

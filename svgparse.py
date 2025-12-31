from joystick_diagrams.template import Template
t = Template(r"C:\Users\theri\projects\joystick-diagrams\templates\WinWing\Guy\throttle.svg")
print('Buttons:', sorted(t.get_template_buttons()))
print('Axes:   ', sorted(t.get_template_axis()))
print('Hats:   ', sorted(t.get_template_hats()))
print('Modifiers:', sorted(t.get_template_modifiers()))
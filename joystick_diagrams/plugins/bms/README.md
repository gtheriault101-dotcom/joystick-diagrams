# Falcon BMS Plugin — Joystick-Diagrams

A plugin for [Joystick-Diagrams](https://github.com/Rexeh/joystick-diagrams) that parses **Falcon BMS 4.38+** joystick XML configuration files and the `AUTO.KEY` callback label file to produce labelled HOTAS device diagrams.

---

## Logo

![Falcon BMS Plugin Logo](joystick_diagrams/plugins/falcon_bms/assets/falcon_bms_logo.svg)

---

## What it does

Falcon BMS stores joystick button bindings, axis assignments, POV hat directions and slider mappings in per-device XML files inside:

```
<BMS Root>/User/Config/Setup.v100.<DeviceName> {GUID}.xml
```

This plugin:
1. Reads all `Setup.v*.xml` files from the BMS User/Config directory.
2. Cross-references the `AUTO.KEY` / `falconbms.key` file in the same directory to convert raw BMS callback names (e.g. `SimTMSUp`) into human-readable diagram labels (e.g. `TMS Up`).
3. Returns a structured dictionary of device profiles that Joystick-Diagrams can render as printable HOTAS diagrams.

---

## Installation

Copy the `joystick_diagrams/plugins/falcon_bms/` directory into the `plugins/` folder of your Joystick-Diagrams installation.

---

## Usage

### Via Joystick-Diagrams UI

Select **Falcon BMS** from the plugin list, then point the path selector at your BMS `User/Config` directory.

### Standalone / CLI (for testing)

```bash
python falcon_bms.py "C:/Falcon BMS 4.38/User/Config"
```

This prints a JSON representation of all detected device profiles.

---

## BMS 4.38.1 DirectX Numbering

BMS 4.38.1 stores Windows DirectX button numbers offset by **+1** in its XML files. The plugin automatically subtracts 1 to produce zero-based DX indices for Joystick-Diagrams. The output dictionary uses **1-based** button numbers to match what BMS displays to the user.

---

## AUTO.KEY label lookup

The `AUTO.KEY` file contains two types of lines:

| Type | Example | Label used |
|------|---------|------------|
| Keyboard (has quoted description) | `SimRemoveEpuPin -1 0 … "CHIEF: Remove EPU Safety Pin"` | `Remove EPU Safety Pin` |
| Joystick (no description) | `SimTMSUp 159 -1 -2 0 0x0 -1` | `TMS Up` (cleaned callback name) |

Redundant callback prefixes (`Sim`, `OTW`, `AF`, `SetRight`, `SetLeft`, …) are stripped, and CamelCase is expanded to spaced words.

---

## Supported device XML sections

| Section | Notes |
|---------|-------|
| `<axis>` | Up to 8 axes; unnamed axes are skipped |
| `<pov>` | Up to 4 POV hats × 8 directions (N/NE/E/SE/S/SW/W/NW) |
| `<dx>` | Up to 128 DX buttons; `SimDoNothing` assignments skipped |

---

## Running the tests

```bash
cd joystick_diagrams/plugins/falcon_bms
python -m pytest test_falcon_bms.py -v
# or
python test_falcon_bms.py
```

---

## File structure

```
falcon_bms_plugin/
└── joystick_diagrams/
    └── plugins/
        └── falcon_bms/
            ├── __init__.py          # Package exports
            ├── falcon_bms.py        # Main plugin implementation
            ├── test_falcon_bms.py   # Unit + integration tests
            └── assets/
                └── falcon_bms_logo.svg
```

---

## Requirements

- Python 3.11+
- Standard library only (`xml.etree.ElementTree`, `pathlib`, `re`, `logging`, `dataclasses`)
- No third-party dependencies

---

## Compatibility

Tested against Falcon BMS **4.38.1**. Should work with 4.37+ as the XML schema has been stable across those versions.

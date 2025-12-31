import json
import logging
from pathlib import Path

from joystick_diagrams.input.profile_collection import ProfileCollection
from .falconbms_parser import FalconBMSParser
from joystick_diagrams.plugins.plugin_interface import PluginInterface

from .config import settings

_logger = logging.getLogger("__name__")

CONFIG_FILE = "data.json"


class ParserPlugin(PluginInterface):
    def __init__(self):
        super().__init__()
        self.settings = settings
        self.settings.validators.register()
        self.path = None
        self.instance: FalconBMSParser | None = None

    def process(self) -> ProfileCollection:
        return self.instance.process_profiles()

    def set_path(self, path: Path) -> bool:
        try:
            self.instance = FalconBMSParser(path)
            self.path = path
            self.save_plugin_state()

        except Exception as e:
            _logger.error("Exception occured with Falcon BMS:", exc_info=e)
            return False

        return True

    def save_plugin_state(self):
        with open(
            Path.joinpath(self.get_plugin_data_path(), CONFIG_FILE),
            "w",
            encoding="UTF8",
        ) as f:
            f.write(json.dumps({"path": str(self.path)}))

    def load_settings(self) -> None:
        try:
            with open(
                Path.joinpath(self.get_plugin_data_path(), CONFIG_FILE),
                "r",
                encoding="UTF8",
            ) as f:
                data = json.loads(f.read())
                self.path = Path(data["path"]) if data["path"] else None
        except FileNotFoundError:
            pass

    def export_mappings(self, export_path: Path = None) -> bool:
        """Export FalconBMS profile/device mappings to a JSON file.

        If `export_path` is a directory it will write `falconbms_mappings.json` into it.
        If `export_path` is a file path it will use that filename (ensuring .json).
        """
        if not self.instance:
            # Try to recreate instance from saved path
            if self.path and Path(self.path).exists():
                try:
                    self.instance = FalconBMSParser(self.path)
                except Exception as e:
                    _logger.error(f"Failed to create FalconBMSParser for export: {e}")
                    return False
            else:
                _logger.error("No FalconBMS parser instance available for export")
                return False

        try:
            profiles = self.instance.process_profiles()

            # Prepare export_path
            if export_path is None:
                export_path = Path.cwd() / "falconbms_mappings.json"

            export_path = Path(export_path)
            if export_path.is_dir():
                export_file = export_path / "falconbms_mappings.json"
            else:
                export_file = export_path.with_suffix(".json")

            # Build serializable structure
            out = {"profiles": []}
            for profile in profiles.profiles.values():
                p = {"profile_name": profile.name, "devices": []}
                for device in profile.get_devices().values():
                    d = {"guid": device.guid, "name": device.name, "inputs": {}}
                    for input_type, inputs in device.get_inputs().items():
                        d["inputs"][input_type] = []
                        for identifier, input_obj in inputs.items():
                            item = {
                                "id": identifier,
                                "command": input_obj.command,
                                "modifiers": [
                                    {"modifiers": list(m.modifiers), "command": m.command}
                                    for m in input_obj.modifiers
                                ],
                            }
                            d["inputs"][input_type].append(item)
                    p["devices"].append(d)
                out["profiles"].append(p)

            # Ensure directory exists
            export_file.parent.mkdir(parents=True, exist_ok=True)

            with open(export_file, "w", encoding="utf8") as fh:
                json.dump(out, fh, indent=2)

            _logger.info(f"FalconBMS mappings exported to {export_file}")
            return True

        except Exception as e:
            _logger.error(f"Error exporting FalconBMS mappings: {e}", exc_info=True)
            return False

    @property
    def path_type(self):
        return self.FolderPath(
            "Select your Falcon BMS setup file or folder",
            Path.joinpath(Path.home(), ""),
        )

    @property
    def icon(self):
        return f"{Path.joinpath(Path(__file__).parent,self.settings.PLUGIN_ICON)}"


if __name__ == "__main__":
    pass

import logging
import os
import sys
from pathlib import Path

_logger = logging.getLogger(__name__)

JOYSTICK_DIAGRAMS_DATA_DIR = "Joystick Diagrams"


def data_root() -> Path:
    """Returns the user data path for storage of data"""

    root = Path.joinpath(
        Path().home(), "AppData", "Roaming", JOYSTICK_DIAGRAMS_DATA_DIR
    )

    if not root.exists():
        create_directory(root)

    return Path.joinpath(root)


def plugin_data_root() -> Path:
    """Returns the user data path for storage of plugin data"""

    root = Path.joinpath(data_root(), "plugins")
    if not root.is_dir():
        create_directory(root)
    return root


def create_directory(directory) -> None:
    try:
        if not Path(directory).exists():
            Path(directory).mkdir()
    except OSError as error:
        _logger.error(f"Failed to create directory: {directory} with {error}")


def install_root() -> str:
    """Returns the current root directory of the package i.e. installation location

    "" in local development environments
    "path_to_frozen_app_exe" in frozen environment

    """
    return (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(__package__)
    )

# This is just temporary, it accomodates windows filesystem restrictions (it should be improved later)
def sanitize_filename(file_name: str, base_path: str | Path | None = None) -> str:
    """Return a filesystem-safe filename preserving extension.

    If `base_path` is provided, ensure the total path length
    (base_path + os.sep + filename) does not exceed 128 characters.
    If it does, remove digits from the filename; if still too long,
    truncate the filename root to fit.
    """
    import re

    if not file_name:
        return ""

    name = str(file_name)
    name = os.path.basename(name)
    root, ext = os.path.splitext(name)

    # Remove characters except letters, numbers, space, dot, underscore and hyphen
    root = re.sub(r'[^A-Za-z0-9 _\-\.]', '', root)

    # Strip whitespace and dots from start/end
    root = root.strip().strip('.')

    # Reserved Windows filenames
    reserved = {
        'CON', 'PRN', 'AUX', 'NUL',
        *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10)),
    }
    if root.upper() in reserved:
        root = f'_{root}'

    # Helper to build candidate path length
    def candidate_length(candidate_root: str) -> int:
        filename = f"{candidate_root}{ext}"
        if base_path:
            return len(str(Path(base_path) / filename))
        return len(filename)

    # If within 128 chars already, just ensure it's not absurdly long overall
    if candidate_length(root) <= 128:
        # Also cap to typical filesystem limit
        if len(root) + len(ext) > 255:
            root = root[: 255 - len(ext)]
        return f"{root}{ext}"

    # Too long: first attempt to remove digits
    no_digits = re.sub(r"\d", "", root)
    if no_digits and candidate_length(no_digits) <= 128:
        root = no_digits
        return f"{root}{ext}"

    # If still too long or removing digits produced empty name, truncate to fit
    base_len = len(str(base_path)) if base_path else 0
    # Account for path separator
    sep_len = 1 if base_path else 0
    allowed = 128 - base_len - sep_len - len(ext)
    if allowed <= 0:
        # Fallback to a minimal name
        root = "export"
    else:
        # Prefer the version with digits removed (if non-empty), else use original
        chosen = no_digits if no_digits else root
        if len(chosen) > allowed:
            chosen = chosen[:allowed]
        root = chosen

    # Final safety cap for filesystem limits
    if len(root) + len(ext) > 255:
        root = root[: 255 - len(ext)]

    return f"{root}{ext}"

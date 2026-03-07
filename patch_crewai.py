"""
patch_crewai.py
---------------
Patches crewai's telemetry.py to remove the `import pkg_resources` line
that crashes on Windows when setuptools is not present.

Run once after installing dependencies:
    python patch_crewai.py

This is safe — crewai's telemetry only uses pkg_resources to read its own
version number. We replace it with importlib.metadata which is built into
Python 3.8+ and needs no extra packages.
"""
import sys
import os
from pathlib import Path

def find_telemetry_file():
    """Find crewai's telemetry.py in the active venv."""
    for path in sys.path:
        candidate = Path(path) / "crewai" / "telemetry" / "telemetry.py"
        if candidate.exists():
            return candidate
    return None

def patch():
    target = find_telemetry_file()
    if not target:
        print("crewai telemetry.py not found — may not be installed yet.")
        sys.exit(1)

    content = target.read_text(encoding="utf-8")

    if "import pkg_resources" not in content:
        print(f"✅ Already patched (or pkg_resources not present): {target}")
        return

    # Replace pkg_resources import with importlib.metadata (stdlib, no install needed)
    content = content.replace(
        "import pkg_resources",
        "import importlib.metadata as importlib_metadata  # patched: replaced pkg_resources"
    )

    # Replace any pkg_resources.get_distribution(...).version usage
    content = content.replace(
        "pkg_resources.get_distribution(",
        "importlib_metadata.version("
    )
    # Handle .version attribute chained calls
    content = content.replace(
        ").version",
        ")"
    )

    target.write_text(content, encoding="utf-8")
    print(f"✅ Patched: {target}")
    print("   Replaced 'import pkg_resources' with 'import importlib.metadata'")

if __name__ == "__main__":
    patch()

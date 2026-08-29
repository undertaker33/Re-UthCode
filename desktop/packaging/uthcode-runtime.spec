"""PyInstaller onedir specification for the UthCode Desktop Bridge.

The Desktop child speaks JSONL over stdin/stdout, so this is intentionally a
console build.  Electron owns the user-facing window and hides this console
process with ``windowsHide`` when it launches the bundle.
"""

from pathlib import Path


SPEC_ROOT = Path(SPEC).resolve().parent
REPO_ROOT = SPEC_ROOT.parent.parent
SOURCE_ROOT = REPO_ROOT / "src"
ENTRY_POINT = SOURCE_ROOT / "uthcode" / "interfaces" / "desktop" / "__main__.py"
PROMPT_ASSET = SOURCE_ROOT / "uthcode" / "prompt_assets" / "coding_agent.md"

if not ENTRY_POINT.is_file():
    raise FileNotFoundError(f"Desktop Runtime entry point is missing: {ENTRY_POINT}")
if not PROMPT_ASSET.is_file():
    raise FileNotFoundError(f"Desktop Runtime prompt asset is missing: {PROMPT_ASSET}")


analysis = Analysis(
    [str(ENTRY_POINT)],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=[(str(PROMPT_ASSET), "uthcode/prompt_assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="uthcode-desktop-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    analysis.zipfiles,
    name="uthcode-runtime",
)

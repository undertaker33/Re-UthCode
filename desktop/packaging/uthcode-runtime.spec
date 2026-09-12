"""PyInstaller onedir specification for the UthCode Desktop Bridge.

The Desktop child speaks JSONL over stdin/stdout, so this is intentionally a
console build.  Electron owns the user-facing window and hides this console
process with ``windowsHide`` when it launches the bundle.
"""

from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
except ImportError:  # pragma: no cover - only PyInstaller evaluates this file
    collect_dynamic_libs = None


SPEC_ROOT = Path(SPEC).resolve().parent
REPO_ROOT = SPEC_ROOT.parent.parent
SOURCE_ROOT = REPO_ROOT / "src"
ENTRY_POINT = SOURCE_ROOT / "uthcode" / "interfaces" / "desktop" / "__main__.py"
PROMPT_ASSET = SOURCE_ROOT / "uthcode" / "prompt_assets" / "coding_agent.md"

if not ENTRY_POINT.is_file():
    raise FileNotFoundError(f"Desktop Runtime entry point is missing: {ENTRY_POINT}")
if not PROMPT_ASSET.is_file():
    raise FileNotFoundError(f"Desktop Runtime prompt asset is missing: {PROMPT_ASSET}")


def _native_resources(package_name: str, suffixes: set[str], target: str) -> list[tuple[str, str]]:
    """Collect package-local native files used by the Desktop Runtime."""

    try:
        package_spec = __import__("importlib.util").util.find_spec(package_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return []
    if package_spec is None or package_spec.submodule_search_locations is None:
        return []
    root = Path(next(iter(package_spec.submodule_search_locations)))
    return [
        (str(path), target)
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in suffixes
    ]


native_binaries = []
if collect_dynamic_libs is not None:
    for package_name in ("pypdfium2_raw", "winpty"):
        try:
            native_binaries.extend(collect_dynamic_libs(package_name))
        except (ImportError, ModuleNotFoundError):
            pass
# pywinpty also ships the small agent executable beside its extension/DLL.
native_binaries.extend(
    _native_resources("winpty", {".dll", ".pyd", ".exe"}, "winpty")
)
hidden_imports = ["pypdfium2", "pypdfium2_raw", "uthcode.integrations.pdf_worker", "uthcode.integrations.tools.document_workers"]
try:
    if __import__("importlib.util").util.find_spec("winpty") is not None:
        hidden_imports.append("winpty")
except (ImportError, ModuleNotFoundError, ValueError):
    pass


analysis = Analysis(
    [str(ENTRY_POINT)],
    pathex=[str(SOURCE_ROOT)],
    binaries=native_binaries,
    datas=[(str(PROMPT_ASSET), "uthcode/prompt_assets")],
    hiddenimports=hidden_imports,
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

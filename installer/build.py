"""Builds the RekordTrakt installer: dist/RekordTrakt-<version>-setup.exe and its SHA-256.

Needs, on Windows x64:
  - Python 3.13 (64-bit): its runtime is bundled, so build with the Python you want to ship
  - the .NET 10 SDK and the Windows MIDI Services package, for the bridge helper (tools/bridge-helper/README.md)
  - Visual Studio Build Tools with "Desktop development with C++", for the launcher (RekordTrakt.exe)
  - Inno Setup 6 (ISCC.exe on PATH, in its usual folder, or named by the ISCC environment variable)

  python installer/build.py             build, test the bundle, make the installer
  python installer/build.py --no-tests  skip running the test suite on the bundle

The installed app is laid out as:
  RekordTrakt.exe     the launcher: runs the app on runtime\\python313.dll, as RekordTrakt
  runtime\\            Python: the DLLs, the standard library (python313.zip) and python313._pth
  app\\rekordtrakt\\    RekordTrakt itself
  bridge\\             rekordtrakt-bridge.exe (creates the MIDI bridge) and the MIDI Services API
  LICENSE.txt, THIRD-PARTY-NOTICES.txt, licenses\\
"""
import argparse
import compileall
import glob
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP = DIST / "RekordTrakt"
PYTHON = (3, 13)
PYTHON_DLL = "python313.dll"
STDLIB_LEAVE_OUT = {"__pycache__", "site-packages", "test", "idlelib", "tkinter", "turtledemo", "turtle.py",
                    "ensurepip", "venv", "pydoc_data", "sqlite3", "curses", "__phello__", "_pyrepl"}
DLLS_LEAVE_OUT = ("_tkinter", "tcl", "tk86", "_test", "sqlite3", ".ico", ".cat")


def run(cmd, **kwargs):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def version():
    return re.search(r'__version__ = "([^"]+)"', (ROOT / "rekordtrakt" / "__init__.py").read_text())[1]


def check_python():
    if sys.version_info[:2] != PYTHON or struct.calcsize("P") != 8:
        sys.exit(f"Build with 64-bit Python {PYTHON[0]}.{PYTHON[1]}: its runtime is what gets bundled.")


def helper():
    """The bridge helper, self-contained (users need no .NET install)."""
    project = ROOT / "tools" / "bridge-helper" / "RekordTrakt.BridgeHelper.csproj"
    run(["dotnet", "publish", project, "-c", "Release", "-r", "win-x64", "--self-contained", "true", "-p:Platform=x64",
         "-p:PublishSingleFile=true", "-p:PublishTrimmed=true", "-p:DebugType=none", "-o", APP / "bridge"])


def vcvars():
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / \
        "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        sys.exit("Visual Studio Build Tools (C++) are needed for the launcher.")
    found = subprocess.run([vswhere, "-latest", "-products", "*", "-requires",
                            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                           capture_output=True, text=True).stdout.strip()
    path = Path(found) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not found or not path.exists():
        sys.exit("Visual Studio Build Tools with the C++ x64 tools are needed for the launcher.")
    return path


def launcher(ver):
    src = ROOT / "installer" / "launcher"
    parts = (ver.split(".") + ["0", "0", "0"])[:4]
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "version.h").write_text(f'#define VERSION_COMMAS {",".join(parts)}\n#define VERSION_TEXT "{ver}"\n')
        script = Path(tmp, "build.cmd")            # a batch file: cmd /c with quoted paths needs no escaping then
        script.write_text("\r\n".join([
            "@echo off",
            f'call "{vcvars()}" >nul || exit /b 1',
            f'rc /nologo /i "{tmp}" /fo "{tmp}\\RekordTrakt.res" RekordTrakt.rc || exit /b 1',
            f'cl /nologo /O2 /W4 /WX /DUNICODE /D_UNICODE /Fo"{tmp}\\\\" RekordTrakt.c "{tmp}\\RekordTrakt.res" '
            f'/Fe"{APP}\\RekordTrakt.exe" /link /SUBSYSTEM:WINDOWS user32.lib shell32.lib || exit /b 1', ""]),
            encoding="ascii")
        run(["cmd", "/c", script], cwd=src)


def runtime():
    """Python's runtime from the build Python: the DLLs, the extension modules, and the standard library compiled
    into one zip. python313._pth fixes the module path (nothing from the environment or the user)."""
    base = Path(sys.base_prefix)
    rt = APP / "runtime"
    (rt / "DLLs").mkdir(parents=True)
    for name in (PYTHON_DLL, "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        shutil.copy2(base / name, rt / name)
    for f in (base / "DLLs").iterdir():
        if f.is_file() and not any(x in f.name.lower() for x in DLLS_LEAVE_OUT):
            shutil.copy2(f, rt / "DLLs" / f.name)
    with zipfile.PyZipFile(rt / "python313.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for item in sorted((base / "Lib").iterdir()):
            if item.name in STDLIB_LEAVE_OUT:
                continue
            if item.is_dir() and (item / "__init__.py").exists():
                z.writepy(item, filterfunc=lambda p: not any(part in STDLIB_LEAVE_OUT or part.endswith("tests")
                                                               for part in Path(p).parts))
            elif item.suffix == ".py":
                z.writepy(item)
    (rt / "python313._pth").write_text("python313.zip\nDLLs\n..\\app\n", encoding="ascii")


def package():
    dst = APP / "app" / "rekordtrakt"
    shutil.copytree(ROOT / "rekordtrakt", dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if not compileall.compile_dir(dst, quiet=1):
        sys.exit("RekordTrakt didn't compile.")


def notices():
    shutil.copy2(ROOT / "LICENSE", APP / "LICENSE.txt")
    shutil.copy2(ROOT / "installer" / "THIRD-PARTY-NOTICES.txt", APP / "THIRD-PARTY-NOTICES.txt")
    lic = APP / "licenses"
    lic.mkdir()
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", lic / "Python.txt")
    packages = Path(os.environ.get("NUGET_PACKAGES") or Path.home() / ".nuget" / "packages")
    runtime_pack = sorted(glob.glob(str(packages / "microsoft.netcore.app.runtime.win-x64" / "10.*")))
    if not runtime_pack:
        sys.exit("The .NET runtime pack wasn't found in the NuGet cache (build the helper first).")
    shutil.copy2(Path(runtime_pack[-1]) / "LICENSE.TXT", lic / "dotnet-runtime.txt")
    shutil.copy2(Path(runtime_pack[-1]) / "THIRD-PARTY-NOTICES.TXT", lic / "dotnet-runtime-third-party-notices.txt")
    cswinrt = sorted(glob.glob(str(packages / "microsoft.windows.cswinrt" / "*" / "LICENSE")))
    if not cswinrt:
        sys.exit("The C#/WinRT package wasn't found in the NuGet cache (build the helper first).")
    shutil.copy2(cswinrt[-1], lic / "CsWinRT.txt")
    shutil.copy2(cswinrt[-1], lic / "Windows-MIDI-Services.txt")      # the same MIT terms, Microsoft Corporation


def test_bundle():
    """Imports every module and runs the test suite on the bundled runtime and the bundled copy of RekordTrakt.
    A console python.exe is borrowed for this and removed again: the installed app is RekordTrakt.exe only."""
    py = APP / "runtime" / "python.exe"
    shutil.copy2(Path(sys.base_prefix) / "python.exe", py)
    try:
        run([py, "-I", "-c", "import importlib, pkgutil, rekordtrakt; "
             "[importlib.import_module(m.name) for m in pkgutil.walk_packages(rekordtrakt.__path__, 'rekordtrakt.') "
             "if not m.name.endswith('__main__')]"])
        run([py, "-I", ROOT / "installer" / "run_tests.py", ROOT / "tests"])
    finally:
        py.unlink()
        for cache in APP.rglob("__pycache__"):
            if "app" not in cache.relative_to(APP).parts[:1]:
                shutil.rmtree(cache, ignore_errors=True)


def iscc():
    candidates = [os.environ.get("ISCC"), shutil.which("iscc"),
                  Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                  Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"]
    found = next((Path(c) for c in candidates if c and Path(c).exists()), None)
    if not found:
        sys.exit("Inno Setup 6 (ISCC.exe) wasn't found: install it, or set ISCC to its path.")
    return found


def installer(ver):
    run([iscc(), f"/DAppVersion={ver}", ROOT / "installer" / "RekordTrakt.iss"])
    setup = DIST / f"RekordTrakt-{ver}-setup.exe"
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    (DIST / f"{setup.name}.sha256").write_text(f"{digest}  {setup.name}\n", encoding="ascii")
    print(f"{setup} ({setup.stat().st_size / 1e6:.1f} MB)\nSHA-256 {digest}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-tests", action="store_true", help="don't run the test suite on the bundle")
    args = p.parse_args()
    check_python()
    ver = version()
    if DIST.exists():
        shutil.rmtree(DIST)
    APP.mkdir(parents=True)
    helper()
    launcher(ver)
    runtime()
    package()
    notices()
    if not args.no_tests:
        test_bundle()
    installer(ver)


if __name__ == "__main__":
    main()

# PyInstaller build of the InvestIQ Windows app (run from packaging/windows: pyinstaller investiq.spec).
# Expects the dashboard (Next.js standalone build) in build/dashboard and node.exe in build/node.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)
REPO = HERE.parents[1]
BACKEND = REPO / "backend"

# The MCP server is not part of the desktop app (it needs the optional "mcp" extra).
hidden = ([m for m in collect_submodules("investiq") if m != "investiq.mcp_server"] + collect_submodules("uvicorn")
          + collect_submodules("alembic") + ["sqlalchemy.dialects.sqlite"])
datas = (collect_data_files("investiq")  # seed lists, AI prompts, report templates
         + collect_data_files("tzdata")  # time zones (Windows has no system tz database)
         + [(str(BACKEND / "alembic.ini"), "."),
            (str(BACKEND / "migrations"), "migrations"),
            (str(REPO / "config" / "model_pricing.yaml"), "config"),
            (str(HERE / "build" / "dashboard"), "dashboard"),
            (str(HERE / "build" / "node"), "node")])
excludes = ["tkinter", "pytest", "mcp"]


def analysis(script):
    return Analysis([str(HERE / script)], pathex=[str(BACKEND)], hiddenimports=hidden, datas=datas,
                    excludes=excludes, noarchive=False)


a_main = analysis("launcher.py")
a_bg = analysis("launcher_background.py")

VERSION_FILE = str(HERE / "version_info.txt")  # publisher/product details shown in the file's properties
exe_main = EXE(PYZ(a_main.pure), a_main.scripts, [], exclude_binaries=True, name="InvestIQ", console=True,
               upx=False, version=VERSION_FILE)
exe_bg = EXE(PYZ(a_bg.pure), a_bg.scripts, [], exclude_binaries=True, name="InvestIQ-Background",
             console=False, upx=False, version=VERSION_FILE)

COLLECT(exe_main, a_main.binaries, a_main.datas, exe_bg, a_bg.binaries, a_bg.datas, name="InvestIQ", upx=False)

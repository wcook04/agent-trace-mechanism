"""Build the workbench for this Mac's architecture, without a runtime checkout."""

from pathlib import Path
import subprocess
import sys
import sysconfig
from importlib.metadata import distribution
import tempfile

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("Build the macOS application on a Mac.")
    with tempfile.TemporaryDirectory(prefix="agent-trace-build-") as tmp:
        entry = Path(tmp) / "launcher.py"
        entry.write_text(
            "from trace_mechanism.workbench.desktop import launch\nlaunch()\n"
        )
        notices = Path(tmp) / "notices"
        notices.mkdir()
        (notices / "Python-LICENSE.txt").write_bytes(
            (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt").read_bytes()
        )
        for name in (
            "pywebview",
            "pyobjc-core",
            "pyobjc-framework-Cocoa",
            "pyobjc-framework-WebKit",
            "pyobjc-framework-Quartz",
            "pyobjc-framework-Security",
            "pyobjc-framework-UniformTypeIdentifiers",
            "bottle",
            "proxy_tools",
            "typing_extensions",
            "pyinstaller",
        ):
            dep = distribution(name)
            (notices / (name + "-METADATA.txt")).write_text(
                dep.read_text("METADATA") or ""
            )
            for f in dep.files or ():
                if "licenses/" in str(f):
                    (notices / (name + "-" + f.name)).write_bytes(
                        dep.locate_file(f).read_bytes()
                    )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--windowed",
                "--onedir",
                "--name",
                "Agent Trace Structurer",
                "--osx-bundle-identifier",
                "io.github.wcook04.agent-trace",
                "--icon",
                str(ROOT / "tools/macos/AgentTrace.icns"),
                "--add-data",
                str(notices) + ":notices",
                "--collect-data",
                "trace_mechanism",
                "--exclude-module",
                "mcp",
                "--exclude-module",
                "pytest",
                "--add-data",
                str(ROOT / "NOTICE") + ":notices",
                "--add-data",
                str(ROOT / "LICENSE") + ":notices",
                "--workpath",
                str(Path(tmp) / "build"),
                "--specpath",
                tmp,
                "--distpath",
                str(ROOT / "dist"),
                str(entry),
            ],
            check=True,
        )

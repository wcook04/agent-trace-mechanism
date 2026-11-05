"""Build the workbench for this Mac's architecture, without a runtime checkout."""

import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import zipfile
import subprocess
import sys
import sysconfig
from importlib.metadata import distribution
import tempfile

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("Build the macOS application on a Mac.")
    with tempfile.TemporaryDirectory(prefix="agent-trace-build-") as tmp:
        git = ["git", "-C", str(ROOT)]
        if subprocess.check_output([*git, "status", "--porcelain"]):
            raise SystemExit(
                "Commit the candidate changes or build from a clean clone."
            )
        revision = subprocess.check_output(
            [*git, "rev-parse", "HEAD"], text=True
        ).strip()
        output = ROOT / "dist"
        output.mkdir(exist_ok=True)
        source_zip = Path(tmp) / "Agent-Trace-source.zip"
        subprocess.run(
            [*git, "archive", "--format=zip", "-o", source_zip, revision], check=True
        )
        export = Path(tmp) / "export"
        with zipfile.ZipFile(source_zip) as archive:
            archive.extractall(export)
        src = export / "src"
        entry = src / "launcher.py"
        entry.write_text(
            "from trace_mechanism.workbench.desktop import launch\nlaunch()\n"
        )
        notices = Path(tmp) / "notices"
        notices.mkdir()
        (notices / "Python-LICENSE.txt").write_bytes(
            (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt").read_bytes()
        )
        versions = {}
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
            versions[name] = dep.version
            (notices / (name + "-METADATA.txt")).write_text(
                dep.read_text("METADATA") or ""
            )
            for f in dep.files or ():
                if "licenses/" in str(f):
                    (notices / (name + "-" + f.name)).write_bytes(
                        dep.locate_file(f).read_bytes()
                    )
        if (
            subprocess.check_output(
                [*git, "rev-parse", "--is-shallow-repository"], text=True
            ).strip()
            == "true"
        ):
            raise SystemExit(
                "Use a full Git checkout to assign the commit build number."
            )
        with (export / "pyproject.toml").open("rb") as project:
            version = tomllib.load(project)["project"]["version"]
        build_number = subprocess.check_output(
            [*git, "rev-list", "--count", revision], text=True
        ).strip()
        build_info = {
            "version": version,
            "build_number": build_number,
            "revision": revision,
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "macos": platform.mac_ver()[0],
            "dependencies": versions,
        }
        (notices / "build.json").write_text(json.dumps(build_info, indent=2) + "\n")
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
                str(export / "tools/macos/AgentTrace.icns"),
                "--add-data",
                str(notices) + ":notices",
                "--paths",
                str(src),
                "--collect-data",
                "trace_mechanism",
                "--exclude-module",
                "mcp",
                "--exclude-module",
                "pytest",
                "--add-data",
                str(export / "NOTICE") + ":notices",
                "--add-data",
                str(export / "LICENSE") + ":notices",
                "--workpath",
                str(Path(tmp) / "build"),
                "--specpath",
                tmp,
                "--distpath",
                str(ROOT / "dist"),
                str(entry),
            ],
            check=True,
            cwd=export,
            env={**os.environ, "PYTHONPATH": str(src)},
        )
        # Verify the actual module graph, even when a different wheel is installed.
        toc = next((Path(tmp) / "build").rglob("PYZ-00.toc"))
        modules = ast.literal_eval(toc.read_text())[1]
        sources = [
            Path(path)
            for name, path, kind in modules
            if name == "trace_mechanism" or name.startswith("trace_mechanism.")
        ]
        if not sources or any(
            not path.is_relative_to(src.resolve())
            for path in map(Path.resolve, sources)
        ):
            raise SystemExit(
                "Frozen reader modules did not come from the archived revision."
            )
        app = output / "Agent Trace Structurer.app"
        info_path = app / "Contents/Info.plist"
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleShortVersionString=version, CFBundleVersion=build_number)
        info_path.write_bytes(plistlib.dumps(info))
        subprocess.run(["codesign", "--force", "--sign", "-", app], check=True)
        assets = app / "Contents/Resources/trace_mechanism/workbench"
        for asset in (src / "trace_mechanism/workbench").rglob("*"):
            if asset.is_file() and asset.suffix in (".html", ".js", ".mjs", ".md"):
                if (
                    assets / asset.relative_to(src / "trace_mechanism/workbench")
                ).read_bytes() != asset.read_bytes():
                    raise SystemExit(
                        "Frozen workbench assets differ from the source archive."
                    )
        subprocess.run(["codesign", "--verify", "--deep", "--strict", app], check=True)
        candidate = output / ("candidate-" + revision[:12])
        candidate.mkdir(exist_ok=True)
        zipped = Path(tmp) / (
            "Agent-Trace-Structurer-macOS-" + platform.machine() + ".zip"
        )
        subprocess.run(["ditto", "-c", "-k", "--keepParent", app, zipped], check=True)
        hashes = {}
        for artifact in (zipped, source_zip):
            hashes[artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            shutil.copyfile(artifact, candidate / artifact.name)
        receipt = {
            **build_info,
            "sha256": hashes,
            "signing": "ad hoc",
            "notarized": False,
        }
        (candidate / "build-receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        print(candidate)

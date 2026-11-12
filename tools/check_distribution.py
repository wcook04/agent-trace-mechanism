#!/usr/bin/env python3
"""Build an sdist and wheel, then exercise the installed wheel outside the checkout."""

from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-trace-package-") as directory:
        scratch = Path(directory)
        # build's default builds the wheel from the sdist, checking both artifacts.
        run(sys.executable, "-m", "build", "--outdir", str(scratch / "dist"), cwd=ROOT)
        (wheel,) = (scratch / "dist").glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            payload = {
                name
                for name in archive.namelist()
                if name.startswith("trace_mechanism/")
            }
            expected = {
                path.relative_to(ROOT / "src").as_posix(): path
                for path in (ROOT / "src/trace_mechanism").rglob("*")
                if path.is_file()
                and path.suffix in (".py", ".js", ".mjs", ".html", ".md")
            }
            assert payload == set(expected), (
                "Wheel package inventory differs from source"
            )
            for name, path in expected.items():
                assert archive.read(name) == path.read_bytes(), (
                    f"Changed package bytes: {name}"
                )
            for name in ("LICENSE", "NOTICE"):
                (member,) = (
                    p for p in archive.namelist() if p.endswith("/licenses/" + name)
                )
                assert archive.read(member) == (ROOT / name).read_bytes()

        venv.EnvBuilder(with_pip=True).create(scratch / "venv")
        python = (
            scratch
            / "venv"
            / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )
        run(str(python), "-m", "pip", "install", f"{wheel}[mcp,test]", cwd=scratch)
        digest = hashlib.sha256(
            (ROOT / "src/trace_mechanism/structurer.mjs").read_bytes()
        ).hexdigest()
        run(
            str(python),
            "-I",
            "-c",
            (
                "from importlib.resources import files; import hashlib; "
                f"assert hashlib.sha256(files('trace_mechanism').joinpath('structurer.mjs').read_bytes()).hexdigest() == {digest!r}"
            ),
            cwd=scratch,
        )
        for module in (
            "trace_mechanism",
            "trace_mechanism.setup",
            "trace_mechanism.mcp_server",
        ):
            run(str(python), "-I", "-m", module, "--help", cwd=scratch)

        # Reuse the real stdio contract check with only its public input/output files.
        for name in (
            "tools/record_native_contract.py",
            "examples/native-command.jsonl",
            "examples/native-command-response.json",
        ):
            destination = scratch / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        run(
            str(python),
            "-I",
            str(scratch / "tools/record_native_contract.py"),
            "--check",
            cwd=scratch,
        )
        manifest = scratch / "selected chats.json"
        run(
            str(python),
            "-I",
            "-m",
            "trace_mechanism.setup",
            "register",
            str(scratch / "examples/native-command.jsonl"),
            "--manifest",
            str(manifest),
            cwd=scratch,
        )
        run(
            str(python),
            "-I",
            "-m",
            "trace_mechanism.setup",
            "verify",
            "--manifest",
            str(manifest),
            cwd=scratch,
        )
        # Only installed wheel bytes are importable. Each provider has its own
        # empty user home, without the other provider's directory or executable.
        for fixture in ("examples/native-command.jsonl", "tests/fixtures/claude.jsonl"):
            home = scratch / (
                "codex user" if fixture.startswith("examples") else "claude user"
            )
            folder = home / (
                ".codex/sessions"
                if fixture.startswith("examples")
                else ".claude/projects"
            )
            folder.mkdir(parents=True)
            source = folder / "chat.jsonl"
            shutil.copyfile(ROOT / fixture, source)
            env = {
                **os.environ,
                "HOME": str(home),
                "USERPROFILE": str(home),
                "PATH": str(python.parent),
            }
            for var in (
                "CODEX_HOME",
                "CLAUDE_CONFIG_DIR",
                "AGENT_TRACE_PROMPTS",
                "PYTHONPATH",
            ):
                env.pop(var, None)
            manifest = home / "selected.json"
            for args in (
                [
                    "-m",
                    "trace_mechanism.setup",
                    "register",
                    str(source),
                    "--manifest",
                    str(manifest),
                ],
                ["-m", "trace_mechanism.setup", "verify", "--manifest", str(manifest)],
                [
                    "-c",
                    "from trace_mechanism.workbench.server import start; "
                    "from urllib.request import Request,urlopen; import threading,json; "
                    "s,u=start(); threading.Thread(target=s.serve_forever,daemon=True).start(); "
                    "assert b'Missions' in urlopen(s.origin).read(); "
                    "assert len(json.load(urlopen(Request(s.origin+'/mission-index',headers={'X-Agent-Trace-Key':s.token})))['index']['active_rows'])==1; "
                    "s.shutdown(); s.server_close()",
                ],
            ):
                subprocess.run(
                    [str(python), "-I", *args], cwd=home, env=env, check=True
                )
        # Replay the customer journeys against the installed wheel, not imports
        # from the source checkout. Copy only the tests and their public fixtures.
        for relative in (
            Path("tests/test_workbench.py"),
            Path("tests/fixtures/claude.jsonl"),
            Path("examples/codex.jsonl"),
            *(p.relative_to(ROOT) for p in (ROOT / "examples/launch-review").glob("*.jsonl")),
        ):
            destination = scratch / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        user_home = scratch / "installed user"
        launch_dir = scratch / "unrelated launch directory"
        user_home.mkdir()
        launch_dir.mkdir()
        env = {**os.environ, "HOME": str(user_home), "USERPROFILE": str(user_home),
               "PATH": str(python.parent), "PYTHONNOUSERSITE": "1"}
        for var in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "AGENT_TRACE_PROMPTS", "PYTHONPATH", "PYTHONHOME",
                    "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            env.pop(var, None)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        subprocess.run(
            [str(python), "-I", "-c",
             "from pathlib import Path; import sys, trace_mechanism; "
             "assert Path(trace_mechanism.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())"],
            cwd=launch_dir, env=env, check=True,
        )
        subprocess.run(
            [str(python), "-I", "-m", "pytest", "--import-mode=importlib", "-q",
             str(scratch / "tests/test_workbench.py")],
            cwd=launch_dir, env=env, check=True,
        )
        print(
            "Distribution passed: sdist, wheel bytes, licence notices, installed resource, CLI, MCP retrieval and installed workbench journeys."
        )


if __name__ == "__main__":
    main()

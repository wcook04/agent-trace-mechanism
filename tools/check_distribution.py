#!/usr/bin/env python3
"""Build an sdist and wheel, then exercise the installed wheel outside the checkout."""
from pathlib import Path
import hashlib
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
        wheel, = (scratch / "dist").glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            payload = {name for name in archive.namelist() if name.startswith("trace_mechanism/")}
            expected = {
                str(path.relative_to(ROOT / "src")): path
                for path in (ROOT / "src/trace_mechanism").iterdir()
                if path.is_file() and path.suffix in (".py", ".mjs")
            }
            assert payload == set(expected), "Wheel package inventory differs from source"
            for name, path in expected.items():
                assert archive.read(name) == path.read_bytes(), f"Changed package bytes: {name}"
            for name in ("LICENSE", "NOTICE"):
                member, = (p for p in archive.namelist() if p.endswith("/licenses/" + name))
                assert archive.read(member) == (ROOT / name).read_bytes()

        venv.EnvBuilder(with_pip=True).create(scratch / "venv")
        python = scratch / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        run(str(python), "-m", "pip", "install", f"{wheel}[mcp]", cwd=scratch)
        digest = hashlib.sha256((ROOT / "src/trace_mechanism/structurer.mjs").read_bytes()).hexdigest()
        run(str(python), "-I", "-c", (
            "from importlib.resources import files; import hashlib; "
            f"assert hashlib.sha256(files('trace_mechanism').joinpath('structurer.mjs').read_bytes()).hexdigest() == {digest!r}"
        ), cwd=scratch)
        for module in ("trace_mechanism", "trace_mechanism.setup", "trace_mechanism.mcp_server"):
            run(str(python), "-I", "-m", module, "--help", cwd=scratch)

        # Reuse the real stdio contract check with only its public input/output files.
        for name in ("tools/record_native_contract.py", "examples/native-command.jsonl",
                     "examples/native-command-response.json"):
            destination = scratch / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        run(str(python), "-I", str(scratch / "tools/record_native_contract.py"), "--check", cwd=scratch)
        manifest = scratch / "selected chats.json"
        run(str(python), "-I", "-m", "trace_mechanism.setup", "register",
            str(scratch / "examples/native-command.jsonl"), "--manifest", str(manifest), cwd=scratch)
        run(str(python), "-I", "-m", "trace_mechanism.setup", "verify",
            "--manifest", str(manifest), cwd=scratch)
        print("Distribution passed: sdist, wheel bytes, licence notices, installed resource, CLI and MCP retrieval.")


if __name__ == "__main__":
    main()

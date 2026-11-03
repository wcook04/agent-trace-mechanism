import importlib.util
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('install_skill', ROOT / 'tools/install_skill.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@pytest.mark.parametrize('host', ['codex', 'claude'])
@pytest.mark.parametrize('scope', ['user', 'project'])
def test_complete_portable_copy_survives_source_removal(tmp_path, monkeypatch, host, scope):
    home = tmp_path / 'new user'
    project = tmp_path / 'working project'
    project.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    source = tmp_path / 'disposable source'
    shutil.copytree(ROOT / 'skills/agent-trace', source)
    expected = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    target = installer.destination(host, scope, project if scope == 'project' else None)
    expected_root = project if scope == 'project' else home
    assert target == expected_root / ('.agents' if host == 'codex' else '.claude') / 'skills/agent-trace'
    installer.install(target, source)
    shutil.rmtree(source)
    actual = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
    assert actual == expected
    assert actual[Path('LICENSE')] == (ROOT / 'LICENSE').read_bytes()
    # Relative references still resolve after copying, without the source checkout.
    import re
    for ref in re.findall(r'\]\((references/[^)]+)\)', (target / 'SKILL.md').read_text()):
        assert (target / ref).is_file()


def test_installer_preserves_existing_skill_and_unrelated_files(tmp_path):
    target = tmp_path / 'skills/agent-trace'
    target.mkdir(parents=True)
    (target / 'SKILL.md').write_text('my edited skill')
    other = target.parent / 'other-skill'
    other.mkdir()
    with pytest.raises(FileExistsError):
        installer.install(target)
    assert (target / 'SKILL.md').read_text() == 'my edited skill'
    assert other.is_dir()


def test_explicit_project_and_custom_locations(tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'work profile'))
    assert installer.destination('claude', 'user') == tmp_path / 'work profile/skills/agent-trace'
    with pytest.raises(ValueError, match='requires --project'):
        installer.destination('codex', 'project')
    assert installer.destination('codex', 'user', skills_dir=tmp_path) == tmp_path / 'agent-trace'


def test_dry_run_does_not_create_destination(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['install_skill', '--host', 'codex', '--skills-dir', str(tmp_path / 'absent'), '--dry-run'])
    installer.main()
    assert 'Would install' in capsys.readouterr().out
    assert not (tmp_path / 'absent').exists()

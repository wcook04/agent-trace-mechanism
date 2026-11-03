import json
from pathlib import Path
import pytest
from trace_mechanism.setup import register

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('provider,variable,child', [
    ('codex', 'CODEX_HOME', 'sessions'), ('claude', 'CLAUDE_CONFIG_DIR', 'projects')])
def test_discovery_uses_the_configured_home(tmp_path, monkeypatch, capsys, provider, variable, child):
    from trace_mechanism.setup import main
    folder = tmp_path / 'nonstandard profile with spaces'
    histories = folder / child
    histories.mkdir(parents=True)
    fixture = ROOT / ('examples/native-command.jsonl' if provider == 'codex' else 'tests/fixtures/claude.jsonl')
    source = histories / 'selected.jsonl'
    source.write_bytes(fixture.read_bytes())
    monkeypatch.setenv(variable, str(folder))
    monkeypatch.setattr('sys.argv', ['setup', 'list', '--provider', provider])
    main()
    assert json.loads(capsys.readouterr().out)[0]['path'] == str(source)


def test_connection_keeps_venv_executable_and_absolute_manifest(tmp_path, monkeypatch):
    from trace_mechanism.setup import connection
    folder = tmp_path / 'another project'
    folder.mkdir()
    manifest = folder / 'chosen chats.json'
    register([ROOT / 'examples/native-command.jsonl'], manifest)
    executable = folder / 'venv python'
    executable.symlink_to(Path(__import__('sys').executable))
    monkeypatch.setattr('sys.executable', str(executable))
    monkeypatch.chdir(folder)
    config = connection(Path('chosen chats.json'))
    assert config['command'] == str(executable)
    assert config['args'][-1] == str(manifest)


def test_verify_mixed_histories_from_unrelated_directory(tmp_path, monkeypatch):
    import asyncio
    from trace_mechanism.setup import verify
    folder = tmp_path / 'records with spaces'
    folder.mkdir()
    sources = []
    for provider, fixture in [('codex', 'examples/native-command.jsonl'), ('claude', 'tests/fixtures/claude.jsonl')]:
        source = folder / (provider + '.jsonl')
        source.write_bytes((ROOT / fixture).read_bytes())
        sources.append(source)
    manifest = folder / 'chosen chats.json'
    register(sources, manifest)
    other = tmp_path / 'different working project'
    other.mkdir()
    monkeypatch.chdir(other)
    result = asyncio.run(verify(manifest))
    assert result['ok'] and result['sessions_read'] == 2
    assert 'read_trace_item' in result['tools']


def test_verify_does_not_claim_success_without_a_history(tmp_path):
    import asyncio
    from trace_mechanism.setup import verify
    manifest = tmp_path / 'empty.json'
    manifest.write_text('[]')
    with pytest.raises(ValueError, match='at least one history'):
        asyncio.run(verify(manifest))


def test_verify_cli_fails_for_missing_source_without_printing_contents(tmp_path, monkeypatch, capsys):
    from trace_mechanism.setup import main
    manifest = tmp_path / 'missing.json'
    manifest.write_text(json.dumps([{'provider':'codex','session_id':'missing','title':'Private title',
                                     'path':str(tmp_path / 'missing.jsonl')}]))
    monkeypatch.setattr('sys.argv', ['setup', 'verify', '--manifest', str(manifest)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert 'Private title' not in output.out + output.err
    assert 'verification failed' in output.err

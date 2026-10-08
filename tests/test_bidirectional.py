import asyncio
import sys
import pytest
from conftest import voices


@pytest.mark.asyncio
async def test_requires_generative(plugin):
    tts, _ = plugin
    with pytest.raises(ValueError, match='generative'):
        await anext(tts.stream_text(None))


def configure(tts, stub, tmp_path, source):
    # Use the normal discovery stub with a separately selected generative client.
    voices(stub, 'en-US', ('Matthew',))
    tts.describe_voices('en-US')
    tts.engine = 'generative'
    tts.describe_voices = lambda *a, **k: {'Voices': [{'Id': 'Matthew'}]}
    path = tmp_path / 'helper.py'
    path.write_text(source)
    tts.config['bidirectional_command'] = [sys.executable, str(path)]
    tts.config['bidirectional_timeout'] = 1


@pytest.mark.asyncio
async def test_audio_arrives_before_input_complete(plugin, tmp_path):
    tts, stub = plugin
    configure(tts, stub, tmp_path, '''import sys,json
header=json.loads(sys.stdin.readline())
assert header['request']['Engine']=='generative'
for line in sys.stdin:
 print(json.loads(line)['text'],end='',flush=True)
''')
    received = asyncio.Event()
    async def text():
        yield 'Bonjour'
        await received.wait()
        yield ' encore'
    chunks = tts.stream_text(text(), 'en-US')
    assert await anext(chunks) == b'Bonjour'
    received.set()
    assert b''.join([c async for c in chunks]) == b' encore'


@pytest.mark.asyncio
async def test_producer_failure_propagates_and_child_is_reaped(plugin, tmp_path):
    tts, stub = plugin
    configure(tts, stub, tmp_path, 'import time; time.sleep(30)')
    async def text():
        raise ValueError('source failed')
        yield ''
    with pytest.raises(ValueError, match='source failed'):
        await anext(tts.stream_text(text(), 'en-US'))


@pytest.mark.asyncio
async def test_helper_error_surfaces(plugin, tmp_path):
    tts, stub = plugin
    configure(tts, stub, tmp_path, 'import sys; sys.stdin.read(); sys.exit(2)')
    async def text():
        yield 'hello'
    with pytest.raises(RuntimeError, match='exit 2'):
        await anext(tts.stream_text(text(), 'en-US'))


@pytest.mark.asyncio
async def test_consumer_close_reaps_helper_and_cancels_producer(plugin, tmp_path, monkeypatch):
    import ovos_tts_plugin_polly.bidirectional as bridge
    tts, stub = plugin
    configure(tts, stub, tmp_path, '''import sys,time
sys.stdin.readline()
sys.stdin.readline()
print('audio',end='',flush=True)
time.sleep(30)
''')
    processes = []
    original = asyncio.create_subprocess_exec
    async def capture(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(bridge.asyncio, 'create_subprocess_exec', capture)
    closed = asyncio.Event()
    async def text():
        try:
            yield 'Hello'
            await asyncio.Event().wait()
        finally:
            closed.set()
    chunks = tts.stream_text(text(), 'en-US')
    assert await anext(chunks) == b'audio'
    await chunks.aclose()
    assert closed.is_set()
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_output_timeout_reaps_helper(plugin, tmp_path, monkeypatch):
    import ovos_tts_plugin_polly.bidirectional as bridge
    tts, stub = plugin
    configure(tts, stub, tmp_path, 'import sys,time; sys.stdin.read(); time.sleep(30)')
    tts.config['bidirectional_timeout'] = 0.1
    processes = []
    original = asyncio.create_subprocess_exec
    async def capture(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(bridge.asyncio, 'create_subprocess_exec', capture)
    async def text():
        yield 'Hello'
    with pytest.raises(asyncio.TimeoutError):
        await anext(tts.stream_text(text(), 'en-US'))
    assert processes[0].returncode is not None


@pytest.mark.parametrize('token', [None, 'fresh-session-token'])
def test_helper_uses_python_identity_over_ambient_profile(plugin, monkeypatch, token):
    """Profiles and stale tokens cannot override the credentials used for discovery."""
    import os
    from botocore.credentials import Credentials
    from ovos_tts_plugin_polly.bidirectional import _helper_environment
    tts, _ = plugin
    tts.config['profile_name'] = 'configured-profile'
    monkeypatch.setenv('AWS_PROFILE', 'ambient-profile')
    monkeypatch.setenv('AWS_DEFAULT_PROFILE', 'legacy-profile')
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'ambient-key')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'ambient-secret')
    monkeypatch.setenv('AWS_SESSION_TOKEN', 'stale-token')
    monkeypatch.setenv('AWS_SECURITY_TOKEN', 'stale-legacy-token')
    monkeypatch.setattr(tts.aws_session, 'get_credentials',
                        lambda: Credentials('python-key', 'python-secret', token))
    environment = _helper_environment(tts)
    assert environment['AWS_ACCESS_KEY_ID'] == 'python-key'
    assert environment['AWS_SECRET_ACCESS_KEY'] == 'python-secret'
    assert environment.get('AWS_SESSION_TOKEN') == token
    assert not {'AWS_PROFILE', 'AWS_DEFAULT_PROFILE', 'AWS_SECURITY_TOKEN'} & environment.keys()
    assert os.environ['AWS_PROFILE'] == 'ambient-profile'
    assert os.environ['AWS_SESSION_TOKEN'] == 'stale-token'


@pytest.mark.asyncio
async def test_each_stream_uses_current_session_credentials(plugin, tmp_path, monkeypatch):
    """A helper subprocess receives freshly resolved tokens on every invocation."""
    from botocore.credentials import Credentials
    tts, stub = plugin
    configure(tts, stub, tmp_path, '''import os,sys
sys.stdin.read()
assert 'AWS_PROFILE' not in os.environ
assert 'AWS_DEFAULT_PROFILE' not in os.environ
assert 'AWS_SECURITY_TOKEN' not in os.environ
sys.stdout.write(os.environ['AWS_SESSION_TOKEN'])
''')
    monkeypatch.setenv('AWS_PROFILE', 'ambient-profile')
    monkeypatch.setenv('AWS_DEFAULT_PROFILE', 'legacy-profile')
    monkeypatch.setenv('AWS_SECURITY_TOKEN', 'stale-token')
    credentials = iter([Credentials('key-one', 'secret', 'token-one'),
                        Credentials('key-two', 'secret', 'token-two')])
    monkeypatch.setattr(tts.aws_session, 'get_credentials', lambda: next(credentials))
    async def text():
        """Supply a complete utterance for the child environment probe."""
        yield 'Hello'
    for expected in (b'token-one', b'token-two'):
        assert b''.join([chunk async for chunk in tts.stream_text(text(), 'en-US')]) == expected


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_starting_helper(plugin, tmp_path, monkeypatch):
    """Missing Python credentials must not fall back to a different Node identity."""
    from unittest.mock import AsyncMock
    from botocore.exceptions import NoCredentialsError
    tts, stub = plugin
    configure(tts, stub, tmp_path, '')
    monkeypatch.setattr(tts.aws_session, 'get_credentials', lambda: None)
    spawn = AsyncMock()
    monkeypatch.setattr('ovos_tts_plugin_polly.bidirectional.asyncio.create_subprocess_exec', spawn)
    with pytest.raises(NoCredentialsError):
        await anext(tts.stream_text(None, 'en-US'))
    spawn.assert_not_called()

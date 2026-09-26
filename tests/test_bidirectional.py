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

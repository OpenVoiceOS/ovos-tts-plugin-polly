import asyncio
import io
import threading
from unittest.mock import Mock
import pytest
from botocore.response import StreamingBody
from conftest import voices
from ovos_tts_plugin_polly import PollyTTS


@pytest.mark.asyncio
async def test_first_chunk_before_complete_download_and_close(plugin):
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    tts.chunk_size = 4
    body = io.BytesIO(b'abcdefgh')
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(body, 8)})
    chunks = tts.stream_tts('Hello', 'en-US')
    assert await anext(chunks) == b'abcd'
    assert body.tell() == 4
    await chunks.aclose()
    assert body.closed


@pytest.mark.asyncio
async def test_network_read_does_not_block_event_loop(plugin):
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    entered, release = threading.Event(), threading.Event()
    class SlowBody(io.BytesIO):
        def read(self, *args):
            entered.set()
            assert release.wait(2)
            return super().read(*args)
    body = SlowBody(b'audio')
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(body, 5)})
    chunks = tts.stream_tts('Hello', 'en-US')
    task = asyncio.create_task(anext(chunks))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.sleep(0)
    finally:
        release.set()
    assert await task == b'audio'
    await chunks.aclose()
    assert body.closed


def test_failed_download_preserves_previous_file(plugin, tmp_path):
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    body = StreamingBody(io.BytesIO(b'short'), 100)
    stub.add_response('synthesize_speech', {'AudioStream': body})
    path = tmp_path / 'audio.mp3'
    path.write_bytes(b'previous')
    with pytest.raises(Exception, match='read'):
        tts.get_tts('Hello', str(path), 'en-US')
    assert path.read_bytes() == b'previous'
    assert list(tmp_path.iterdir()) == [path]
    assert body._raw_stream.closed


@pytest.mark.asyncio
async def test_playback_failure_closes_stream_and_removes_partial(plugin, tmp_path):
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    body = StreamingBody(io.BytesIO(b'audio'), 5)
    stub.add_response('synthesize_speech', {'AudioStream': body})
    tts.callbacks = Mock()
    tts.callbacks.stream_chunk.side_effect = RuntimeError('player stopped')
    with pytest.raises(RuntimeError, match='player stopped'):
        await tts.generate_audio('Hello', str(tmp_path / 'audio.mp3'), plugin_kwargs={'lang': 'en-US'})
    assert body._raw_stream.closed
    assert list(tmp_path.iterdir()) == []
    tts.callbacks.stream_stop.assert_called_once()


def test_aws_default_credential_chain_and_transport(monkeypatch):
    session = Mock()
    monkeypatch.setattr('boto3.Session', session)
    PollyTTS(config={'read_timeout': 8, 'max_attempts': 2})
    session.assert_called_once_with(region_name='us-east-1')
    config = session.return_value.client.call_args.kwargs['config']
    assert config.read_timeout == 8
    assert config.retries == {'mode': 'standard', 'total_max_attempts': 2}
    assert config.tcp_keepalive


def test_temporary_credentials(monkeypatch):
    session = Mock()
    monkeypatch.setattr('boto3.Session', session)
    PollyTTS(config={'access_key_id': 'test', 'secret_access_key': 'test', 'session_token': 'test'})
    assert session.call_args.kwargs['aws_session_token'] == 'test'


@pytest.mark.asyncio
async def test_cancel_during_request_closes_late_response(plugin):
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    entered, release = threading.Event(), threading.Event()
    body = StreamingBody(io.BytesIO(b'audio'), 5)
    def request(**kwargs):
        entered.set()
        release.wait(2)
        return {'AudioStream': body}
    tts.polly.synthesize_speech = request
    chunks = tts.stream_tts('Hello', 'en-US')
    task = asyncio.create_task(anext(chunks))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    for _ in range(100):
        if body._raw_stream.closed:
            break
        await asyncio.sleep(0.01)
    assert body._raw_stream.closed


@pytest.mark.asyncio
async def test_streaming_pcm_saved_with_correct_lengths(plugin, tmp_path):
    import wave
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    tts.output_format, tts.sample_rate, tts.enable_cache = 'pcm', '16000', False
    data = b'\x01\x00' * 10
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(io.BytesIO(data), len(data))})
    path = str(tmp_path / 'test.wav')
    await tts.generate_audio('Hello', path, play_streaming=False, plugin_kwargs={'lang': 'en-US'})
    with wave.open(path) as audio:
        assert audio.getnframes() == 10
        assert audio.readframes(10) == data


@pytest.mark.asyncio
async def test_completed_stream_is_reused_by_framework_cache(plugin, tmp_path, monkeypatch):
    from ovos_plugin_manager.templates.tts import TTSContext
    from ovos_plugin_manager.utils.tts_cache import hash_sentence
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    tts.config.update(preloaded_cache=str(tmp_path), persist_cache=False)
    monkeypatch.setattr('ovos_plugin_manager.utils.tts_cache.get_tmp_cache_dir', lambda *a: str(tmp_path))
    monkeypatch.setattr(TTSContext, '_caches', {})
    ctxt = tts._get_ctxt({'lang': 'en-US'})
    cache = ctxt.get_cache(tts.audio_ext, tts.config)
    path = str(cache.define_audio_file(hash_sentence('Hello')))
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(io.BytesIO(b'audio'), 5)})
    await tts.generate_audio('Hello', path, play_streaming=False, plugin_kwargs=ctxt.synth_kwargs)
    # No AWS response remains: a second synthesis must hit the framework cache.
    audio, _ = tts.synth('Hello', lang='en-US')
    assert str(audio) == path
    assert hash_sentence('Hello') in cache


def test_late_response_closed_after_event_loop_shutdown(plugin):
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    entered, release = threading.Event(), threading.Event()
    body = StreamingBody(io.BytesIO(b'audio'), 5)
    def request(**kwargs):
        entered.set()
        release.wait(2)
        return {'AudioStream': body}
    tts.polly.synthesize_speech = request
    async def cancel_request():
        chunks = tts.stream_tts('Hello', 'en-US')
        task = asyncio.create_task(anext(chunks))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    # asyncio.run closes the loop after cancellation, while the worker is active.
    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        asyncio.run(cancel_request())
    finally:
        release.set()
        timer.join()
    assert body._raw_stream.closed

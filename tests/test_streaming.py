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


@pytest.mark.asyncio
async def test_streaming_persistence_counter_advances_once(plugin, tmp_path, monkeypatch):
    """Registration must not change the cache path chosen for this synthesis."""
    from ovos_plugin_manager.templates.tts import TTSContext
    from ovos_plugin_manager.utils.tts_cache import hash_sentence
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    tts.config.update(preloaded_cache=str(tmp_path / 'persistent'), persist_cache=True, persist_thresh=2)
    monkeypatch.setattr(TTSContext, '_caches', {})
    monkeypatch.setattr('ovos_plugin_manager.utils.tts_cache.get_tmp_cache_dir', lambda *a: str(tmp_path / 'temporary'))
    ctxt = tts._get_ctxt({'lang': 'en-US'})
    cache = ctxt.get_cache(tts.audio_ext, tts.config)
    key = hash_sentence('Hello')
    path = str(cache.define_audio_file(key))
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(io.BytesIO(b'audio'), 5)})
    await tts.generate_audio('Hello', path, play_streaming=False, plugin_kwargs=ctxt.synth_kwargs)
    assert cache._sentence_count[key] == 1
    assert key in cache
    # No synthesis response remains; reuse the completed temporary cache file.
    audio, _ = tts.synth('Hello', lang='en-US')
    assert str(audio) == path
    assert cache._sentence_count[key] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('threaded', [False, True])
async def test_stop_interrupts_stream_and_preserves_completed_file(plugin, tmp_path, threaded):
    """Stop from either thread cancels further chunks and never caches partial audio."""
    tts, _ = plugin
    first = threading.Event()
    closed = asyncio.Event()
    tts.callbacks = Mock()
    tts.callbacks.stream_chunk.side_effect = lambda chunk: first.set()
    async def chunks(*args, **kwargs):
        """Hold the response open after the first playable chunk."""
        try:
            yield b'first'
            await asyncio.Event().wait()
            yield b'second'
        finally:
            closed.set()
    tts.stream_tts = chunks
    target = tmp_path / 'audio.mp3'
    target.write_bytes(b'previous')
    task = asyncio.create_task(tts.generate_audio('Hello', str(target), listen=True))
    assert await asyncio.to_thread(first.wait, 2)
    if threaded:
        await asyncio.to_thread(tts.stop)
    else:
        tts.stop()
    tts.stop()  # Repeated stops must not interrupt cleanup.
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert closed.is_set()
    assert tts.callbacks.stream_chunk.call_count == 1
    tts.callbacks.stream_stop.assert_called_once_with(False, None)
    assert target.read_bytes() == b'previous'
    assert list(tmp_path.iterdir()) == [target]
    assert not tts._active_streams


@pytest.mark.asyncio
async def test_stop_cancels_pending_synthesis_and_closes_late_body(plugin, tmp_path):
    """A stop before the first byte closes responses arriving after cancellation."""
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    entered, release = threading.Event(), threading.Event()
    body = StreamingBody(io.BytesIO(b'audio'), 5)
    def request(**kwargs):
        """Simulate a request already in flight when the user stops speech."""
        entered.set()
        release.wait(2)
        return {'AudioStream': body}
    tts.polly.synthesize_speech = request
    tts.callbacks = Mock()
    task = asyncio.create_task(tts.generate_audio('Hello', str(tmp_path / 'audio.mp3'),
                                                plugin_kwargs={'lang': 'en-US'}, listen=True))
    assert await asyncio.to_thread(entered.wait, 2)
    tts.stop()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    finally:
        release.set()
    for _ in range(100):
        if body._raw_stream.closed:
            break
        await asyncio.sleep(0.01)
    assert body._raw_stream.closed
    tts.callbacks.stream_chunk.assert_not_called()
    tts.callbacks.stream_stop.assert_called_once_with(False, None)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_next_utterance_works_after_stop(plugin, tmp_path):
    """An interruption must not leave the plugin permanently cancelled."""
    tts, _ = plugin
    tts.enable_cache = False
    tts.callbacks = Mock()
    first = threading.Event()
    tts.callbacks.stream_chunk.side_effect = lambda chunk: first.set()
    async def blocked(*args, **kwargs):
        """Keep the first utterance active until interrupted."""
        yield b'first'
        await asyncio.Event().wait()
    tts.stream_tts = blocked
    task = asyncio.create_task(tts.generate_audio('first', str(tmp_path / 'first.mp3')))
    assert await asyncio.to_thread(first.wait, 2)
    tts.stop()
    with pytest.raises(asyncio.CancelledError):
        await task
    async def complete(*args, **kwargs):
        """Provide a subsequent, complete utterance."""
        yield b'complete'
    tts.stream_tts = complete
    target = str(tmp_path / 'second.mp3')
    assert await tts.generate_audio('second', target, listen=True) == target
    assert tts.callbacks.stream_stop.call_args.args == (True, None)
    assert not tts._active_streams


def test_default_player_abort_discards_buffered_audio():
    """The default callback kills the player and suppresses post-stop listening."""
    from ovos_tts_plugin_polly.playback import PollyStreamingCallbacks
    callbacks = PollyStreamingCallbacks(Mock(), play_args=['unused'], tts_config={})
    process = Mock()
    process.stdin.close.side_effect = BrokenPipeError()
    callbacks._process = process
    callbacks.stream_abort()
    callbacks.stream_stop(listen=True)
    process.kill.assert_called_once()
    process.wait.assert_called_once()
    assert callbacks._process is None
    events = [call.args[0].msg_type for call in callbacks.bus.emit.call_args_list]
    assert 'recognizer_loop:audio_output_end' in events
    assert 'mycroft.mic.listen' not in events


@pytest.mark.asyncio
async def test_stop_kills_player_while_buffered_audio_is_draining(plugin, tmp_path):
    """Stop remains effective after downloading ends but before playback finishes."""
    import sys
    from ovos_tts_plugin_polly.playback import PollyStreamingCallbacks
    tts, _ = plugin
    tts.enable_cache = False
    ready = tmp_path / 'player-draining'
    player = ('import sys,time; from pathlib import Path; sys.stdin.buffer.read(); '
              'Path(sys.argv[1]).touch(); time.sleep(30)')
    tts.callbacks = PollyStreamingCallbacks(Mock(), play_args=[sys.executable, '-c', player, str(ready)])
    async def chunks(*args, **kwargs):
        """Finish synthesis immediately so the test observes player draining."""
        yield b'audio'
    tts.stream_tts = chunks
    task = asyncio.create_task(tts.generate_audio('Hello', str(tmp_path / 'audio.mp3'), listen=True))
    try:
        for _ in range(200):
            if ready.exists():
                break
            await asyncio.sleep(0.01)
        assert ready.exists()
        process = tts.callbacks._process
        assert process.poll() is None
        tts.stop()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert process.poll() is not None
        assert tts.callbacks._process is None
        events = [call.args[0].msg_type for call in tts.callbacks.bus.emit.call_args_list]
        assert 'mycroft.mic.listen' not in events
    finally:
        tts.stop()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_ovos_execute_returns_normally_after_user_stop(plugin, tmp_path, monkeypatch):
    """The synchronous OVOS entry point consumes expected cancellation cleanly."""
    from ovos_plugin_manager.templates.tts import TTSContext
    tts, stub = plugin
    voices(stub, 'en-US', ('Matthew',))
    monkeypatch.setattr(TTSContext, '_caches', {})
    monkeypatch.setattr('ovos_plugin_manager.utils.tts_cache.get_tmp_cache_dir', lambda *a: str(tmp_path))
    tts.config.update(enable_streaming=True, preloaded_cache=str(tmp_path / 'persistent'))
    tts.enable_cache = False
    first = threading.Event()
    tts.callbacks = Mock()
    tts.callbacks.stream_chunk.side_effect = lambda chunk: first.set()
    async def chunks(*args, **kwargs):
        """Wait for a stop signal after the initial audio arrives."""
        yield b'first'
        await asyncio.Event().wait()
    tts.stream_tts = chunks
    task = asyncio.create_task(asyncio.to_thread(tts._execute, 'Hello', None, True, lang='en-US'))
    assert await asyncio.to_thread(first.wait, 2)
    tts.stop()
    assert await asyncio.wait_for(task, 2) is None
    assert not tts._active_streams
    tts.callbacks.stream_stop.assert_called_once()


@pytest.mark.asyncio
async def test_stop_during_player_start_cleans_up_late_player(plugin, tmp_path):
    """A player created after interruption is aborted before any audio is delivered."""
    tts, _ = plugin
    entered, release = threading.Event(), threading.Event()
    tts.callbacks = Mock()
    def start(message):
        """Delay player creation until after cancellation has been requested."""
        entered.set()
        assert release.wait(2)
    tts.callbacks.stream_start.side_effect = start
    tts.callbacks.stream_abort.side_effect = release.set
    async def chunks(*args, **kwargs):
        """Audio must never be requested after an interrupted start."""
        raise AssertionError('synthesis started after stop')
        yield b''
    tts.stream_tts = chunks
    task = asyncio.create_task(tts.generate_audio('Hello', str(tmp_path / 'audio.mp3')))
    assert await asyncio.to_thread(entered.wait, 2)
    tts.stop()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    tts.callbacks.stream_chunk.assert_not_called()
    tts.callbacks.stream_stop.assert_called_once_with(False, None)
    assert not list(tmp_path.iterdir())


def test_init_installs_abort_capable_default_callbacks(plugin, monkeypatch):
    """OVOS initialization uses the interruptible player and preserves custom callbacks."""
    from ovos_plugin_manager.templates.tts import StreamingTTS
    from ovos_tts_plugin_polly.playback import PollyStreamingCallbacks
    tts, _ = plugin
    initialize = Mock()
    monkeypatch.setattr(StreamingTTS, 'init', initialize)
    monkeypatch.setattr('ovos_plugin_manager.templates.tts.shutil.which', lambda name: '/usr/bin/ffplay')
    bus = Mock()
    tts.init(bus=bus)
    assert isinstance(initialize.call_args.args[2], PollyStreamingCallbacks)
    custom = Mock()
    tts.init(bus=bus, callbacks=custom)
    assert initialize.call_args.args[2] is custom

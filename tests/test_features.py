import io
import wave
from unittest.mock import Mock
import pytest
from botocore.response import StreamingBody
from conftest import voices
from ovos_tts_plugin_polly import PollyTTS


def test_lexicons_and_rate(plugin):
    tts, stub = plugin
    voices(stub)
    tts.lexicon_names = ['Names']
    request = tts._synthesis_request('Bonjour', 'fr-CA')
    assert request['LexiconNames'] == ['Names']
    assert request['SampleRate'] == '24000'


def test_cache_isolated_by_engine_format_and_lexicon(plugin):
    tts, stub = plugin
    voices(stub)
    ids = [tts._get_ctxt({'lang': 'fr-CA'}).tts_id]
    for attr, value in [('sample_rate', '48000'), ('lexicon_names', ['Names']), ('output_format', 'pcm')]:
        setattr(tts, attr, value)
        ids.append(tts._get_ctxt({'lang': 'fr-CA'}).tts_id)
    assert len(set(ids)) == 4


def test_pcm_has_valid_wav_header(plugin, tmp_path):
    tts, stub = plugin
    voices(stub)
    tts.output_format = 'pcm'
    tts.sample_rate = '16000'
    data = b'\x01\x00' * 10
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(io.BytesIO(data), len(data))}, {
        'Text': 'Bonjour', 'TextType': 'text', 'OutputFormat': 'pcm', 'SampleRate': '16000',
        'Engine': 'neural', 'VoiceId': 'Gabrielle', 'LanguageCode': 'fr-CA'})
    path = str(tmp_path / 'audio.wav')
    tts.get_tts('Bonjour', path, lang='fr-CA')
    with wave.open(path) as audio:
        assert audio.getframerate() == 16000
        assert audio.getnchannels() == 1
        assert audio.readframes(10) == data


def test_speech_marks(plugin):
    tts, stub = plugin
    voices(stub)
    data = b'{"time":0,"type":"word","value":"Bonjour"}\n'
    stream = StreamingBody(io.BytesIO(data), len(data))
    stub.add_response('synthesize_speech', {'AudioStream': stream}, {
        'Text': 'Bonjour', 'TextType': 'text', 'OutputFormat': 'json',
        'Engine': 'neural', 'VoiceId': 'Gabrielle', 'LanguageCode': 'fr-CA',
        'SpeechMarkTypes': ['word']})
    assert tts.get_speech_marks('Bonjour', 'fr-CA', mark_types=['word'])[0]['time'] == 0
    assert stream._raw_stream.closed


@pytest.mark.parametrize('config', [
    {'output_format': 'json'}, {'output_format': 'pcm', 'sample_rate': 48000},
    {'lexicon_names': 'Names'}, {'lexicon_names': ['bad-name']}, {'engine': 'unknown'},
])
def test_invalid_controls_fail_before_aws(config, monkeypatch):
    session = Mock()
    monkeypatch.setattr('boto3.Session', session)
    with pytest.raises(ValueError):
        PollyTTS(config=config)
    session.assert_not_called()


@pytest.mark.parametrize('changed', [
    {'engine': 'generative'}, {'sample_rate': '48000'},
    {'lexicon_names': ['Names']}, {'voice': 'Joanna'},
    {'lang': 'fr-CA'}, {'region': 'us-west-2'},
])
def test_persistent_cache_does_not_cross_synthesis_contexts(plugin, tmp_path, monkeypatch, changed):
    """Restarted contexts synthesize new audio instead of loading incompatible files."""
    from pathlib import Path
    from ovos_plugin_manager.templates.tts import TTSContext
    tts, stub = plugin
    root = tmp_path / 'persistent'
    tts.config.update(preloaded_cache=str(root), persist_cache=True, persist_thresh=1)
    monkeypatch.setattr('ovos_plugin_manager.utils.tts_cache.get_tmp_cache_dir',
                        lambda name: str(tmp_path / 'temporary' / name))
    monkeypatch.setattr(TTSContext, '_caches', {})
    catalog = [
        {'Id': 'Matthew', 'LanguageCode': 'en-US'},
        {'Id': 'Joanna', 'LanguageCode': 'en-US'},
        {'Id': 'Gabrielle', 'LanguageCode': 'fr-CA'},
    ]
    monkeypatch.setattr(tts, 'describe_voices', lambda *a, **k: {'Voices': catalog})
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(io.BytesIO(b'original'), 8)})
    first, _ = tts.synth('Hello', lang='en-US')
    for key, value in changed.items():
        if key not in {'lang', 'voice'}:
            setattr(tts, key, value)
    call_kwargs = {'lang': changed.get('lang', 'en-US'), 'voice': changed.get('voice', 'Matthew')}
    TTSContext._caches.clear()
    stub.add_response('synthesize_speech', {'AudioStream': StreamingBody(io.BytesIO(b'changed'), 7)})
    second, _ = tts.synth('Hello', **call_kwargs)
    assert Path(str(first)).read_bytes() == b'original'
    assert Path(str(second)).read_bytes() == b'changed'
    assert Path(str(first)).parent != Path(str(second)).parent
    assert tts.config['preloaded_cache'] == str(root)
    TTSContext._caches.clear()
    # The same settings still reuse the persisted result after another restart.
    restored, _ = tts.synth('Hello', **call_kwargs)
    assert str(restored) == str(second)


def test_distinct_persistent_roots_do_not_share_in_memory_cache(plugin, tmp_path, monkeypatch):
    """Two configured roots retain separate cache objects for identical voices."""
    from ovos_plugin_manager.templates.tts import TTSContext
    tts, stub = plugin
    voices(stub)
    monkeypatch.setattr(TTSContext, '_caches', {})
    monkeypatch.setattr('ovos_plugin_manager.utils.tts_cache.get_tmp_cache_dir',
                        lambda name: str(tmp_path / 'temporary' / name))
    caches = []
    for name in ('one', 'two'):
        tts.config['preloaded_cache'] = str(tmp_path / name)
        ctxt = tts._get_ctxt({'lang': 'fr-CA'})
        caches.append(ctxt.get_cache(tts.audio_ext))
    assert caches[0] is not caches[1]
    assert caches[0].persistent_cache_dir != caches[1].persistent_cache_dir

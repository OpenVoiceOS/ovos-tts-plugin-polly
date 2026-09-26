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

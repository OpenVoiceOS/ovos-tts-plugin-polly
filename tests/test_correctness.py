import io
import pytest
from botocore.response import StreamingBody
from conftest import voices
from ovos_tts_plugin_polly import PollyTTS


def test_language_selection_and_bilingual_parameter(plugin, tmp_path):
    tts, stub = plugin
    voices(stub)
    stream = StreamingBody(io.BytesIO(b'audio'), 5)
    stub.add_response('synthesize_speech', {'AudioStream': stream}, {
        'Text': 'Bonjour', 'TextType': 'text', 'OutputFormat': 'mp3',
        'Engine': 'neural', 'VoiceId': 'Gabrielle', 'LanguageCode': 'fr-CA', 'SampleRate': '24000'})
    path = tmp_path / 'test.mp3'
    assert tts.get_tts('Bonjour', str(path), lang='fr-ca') == (str(path), None)
    assert path.read_bytes() == b'audio'
    assert stream._raw_stream.closed


def test_explicit_incompatible_voice_rejected(plugin):
    tts, stub = plugin
    voices(stub)
    with pytest.raises(ValueError, match='Matthew'):
        tts._synthesis_request('Bonjour', 'fr-CA', 'Matthew')


def test_discovery_pagination_and_cache(plugin):
    tts, stub = plugin
    params = dict(Engine='neural', LanguageCode='en-US', IncludeAdditionalLanguageCodes=True)
    stub.add_response('describe_voices', {'Voices': [{'Id': 'Matthew'}], 'NextToken': 'next'}, params)
    stub.add_response('describe_voices', {'Voices': [{'Id': 'Joanna'}]}, dict(params, NextToken='next'))
    result = tts.describe_voices('en-us')
    assert [v['Id'] for v in result['Voices']] == ['Matthew', 'Joanna']
    result['Voices'].clear()
    assert len(tts.describe_voices('en-US')['Voices']) == 2


def test_framework_language_does_not_force_default_voice(plugin):
    tts, stub = plugin
    voices(stub)
    assert tts._get_ctxt({'lang': 'fr-CA'}).voice == 'Gabrielle'


@pytest.mark.parametrize('text,expected', [
    ('<speak><amazon:effect name="whispered">He whispered</amazon:effect></speak>',
     '<speak><amazon:effect name="whispered">He whispered</amazon:effect></speak>'),
    ('<whispered>Hello</whispered>', '<speak><amazon:effect name="whispered">Hello</amazon:effect></speak>'),
    ('<break time="1s"/>Hello', '<speak><break time="1s"/>Hello</speak>'),
])
def test_ssml_preserved(text, expected):
    assert PollyTTS._prepare_text(text) == (expected, 'ssml')


def test_plain_text():
    assert PollyTTS._prepare_text('He whispered: 2 < 3') == ('He whispered: 2 < 3', 'text')


@pytest.mark.parametrize('lang,expected', [('arb', 'arb'), ('en-gb-wls', 'en-GB-WLS'), ('zh-zh', 'cmn-CN')])
def test_language_codes(lang, expected):
    assert PollyTTS._language_code(lang) == expected

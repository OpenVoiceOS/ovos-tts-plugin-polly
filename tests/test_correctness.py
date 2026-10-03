import io
import pytest
from botocore.response import StreamingBody
from conftest import voices
from ovos_tts_plugin_polly import PollyTTS


def test_language_selection_and_bilingual_parameter(plugin, tmp_path):
    """A French request selects a French voice and forwards its language to Polly."""
    tts, stub = plugin
    voices(stub)
    stream = StreamingBody(io.BytesIO(b'audio'), 5)
    stub.add_response('synthesize_speech', {'AudioStream': stream}, {
        'Text': 'Bonjour', 'TextType': 'text', 'OutputFormat': 'mp3',
        'Engine': 'neural', 'VoiceId': 'Gabrielle', 'LanguageCode': 'fr-CA'})
    path = tmp_path / 'test.mp3'
    assert tts.get_tts('Bonjour', str(path), lang='fr-ca') == (str(path), None)
    assert path.read_bytes() == b'audio'
    assert stream._raw_stream.closed


def test_explicit_incompatible_voice_rejected(plugin):
    """An explicit voice mismatch fails before any synthesis request is sent."""
    tts, stub = plugin
    voices(stub)
    with pytest.raises(ValueError, match='Matthew'):
        tts._synthesis_request('Bonjour', 'fr-CA', 'Matthew')


def test_discovery_pagination_and_cache(plugin):
    """Discovery combines all pages and protects cached catalog data from caller mutation."""
    tts, stub = plugin
    params = dict(Engine='neural', LanguageCode='en-US', IncludeAdditionalLanguageCodes=True)
    stub.add_response('describe_voices', {'Voices': [{'Id': 'Matthew'}], 'NextToken': 'next'}, params)
    stub.add_response('describe_voices', {'Voices': [{'Id': 'Joanna'}]}, dict(params, NextToken='next'))
    result = tts.describe_voices('en-us')
    assert [v['Id'] for v in result['Voices']] == ['Matthew', 'Joanna']
    result['Voices'].clear()
    assert len(tts.describe_voices('en-US')['Voices']) == 2


def test_framework_language_does_not_force_default_voice(plugin):
    """The OVOS context honors the requested language instead of injecting an English voice."""
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
    """Standard SSML stays intact and legacy fragments become valid speak documents."""
    assert PollyTTS._prepare_text(text) == (expected, 'ssml')


def test_plain_text():
    """Ordinary words and comparison symbols remain plain text."""
    assert PollyTTS._prepare_text('He whispered: 2 < 3') == ('He whispered: 2 < 3', 'text')


@pytest.mark.parametrize('lang,expected', [('arb', 'arb'), ('en-gb-wls', 'en-GB-WLS'), ('zh-zh', 'cmn-CN')])
def test_language_codes(lang, expected):
    """Single-part codes, regional variants, and Chinese aliases normalize consistently."""
    assert PollyTTS._language_code(lang) == expected


@pytest.mark.parametrize('text', ['Mail Tom <tom@example.com>', 'if a <b and c> d', '<server> is down'])
def test_angle_brackets_in_plain_text(text):
    """Email addresses and unrelated angle-bracket tokens must not enable SSML."""
    assert PollyTTS._prepare_text(text) == (text, 'text')


@pytest.mark.parametrize('call_kwargs', [{}, {'lang': None}])
def test_framework_uses_configured_language_without_request_or_session(plugin, monkeypatch, call_kwargs):
    """A configured French locale reaches synthesis when the caller has no locale."""
    tts, stub = plugin
    tts.config.update(lang='fr-CA', voice='Gabrielle')
    monkeypatch.setattr('ovos_plugin_manager.templates.tts.dig_for_message', lambda: None)
    voices(stub)
    ctxt = tts._get_ctxt(call_kwargs)
    assert ctxt.lang.lower() == 'fr-ca'
    assert ctxt.voice == 'Gabrielle'
    assert ctxt.synth_kwargs == {'lang': 'fr-CA', 'voice': 'Gabrielle'}
    assert call_kwargs in ({}, {'lang': None})


@pytest.mark.parametrize('call_kwargs,session_lang,expected', [
    ({'lang': 'fr-CA'}, 'en-US', 'fr-CA'),
    ({}, 'en-US', 'en-US'),
    ({'lang': None}, 'en-US', 'en-US'),
])
def test_request_and_session_language_override_plugin_default(plugin, monkeypatch, call_kwargs, session_lang, expected):
    """Explicit call_kwargs language wins over session language, which wins over config."""
    from types import SimpleNamespace
    tts, stub = plugin
    tts.config.update(lang='fr-CA', voice='Gabrielle')
    monkeypatch.setattr('ovos_plugin_manager.templates.tts.SessionManager.get',
                        lambda message=None: SimpleNamespace(lang=session_lang))
    voice = 'Gabrielle' if expected == 'fr-CA' else 'Matthew'
    voices(stub, expected, (voice,))
    ctxt = tts._get_ctxt(dict(call_kwargs, message=object()))
    assert ctxt.synth_kwargs == {'lang': expected, 'voice': voice}
    assert ctxt.lang.lower() == expected.lower()

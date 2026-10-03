import boto3
import pytest
from botocore.stub import Stubber
from ovos_tts_plugin_polly import PollyTTS


@pytest.fixture
def plugin(monkeypatch):
    """Provide a Polly plugin with an AWS stub that rejects unexpected network requests."""
    client = boto3.client('polly', region_name='us-east-1',
                          aws_access_key_id='testing', aws_secret_access_key='testing')
    monkeypatch.setattr('boto3.Session.client', lambda *a, **k: client)
    tts = PollyTTS(config={'voice': 'Matthew', 'engine': 'neural'})
    with Stubber(client) as stub:
        yield tts, stub
        stub.assert_no_pending_responses()


def voices(stub, lang='fr-CA', ids=('Gabrielle', 'Liam'), **extra):
    """Queue an engine-filtered voice catalog response for synthesis tests."""
    params = dict(Engine='neural', IncludeAdditionalLanguageCodes=True)
    if lang:
        params['LanguageCode'] = lang
    params.update(extra)
    stub.add_response('describe_voices', {'Voices': [
        {'Id': v, 'LanguageCode': lang or 'en-US', 'SupportedEngines': ['neural']}
        for v in ids]}, params)

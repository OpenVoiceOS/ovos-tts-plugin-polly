"""End-to-end TTS intelligibility test for the AWS Polly TTS plugin.

Polly is a cloud engine and needs AWS credentials. When no AWS credentials are
present in the environment the test is skipped rather than hard-failing on the
missing secret. With credentials available, a small fixed set of English
phrases is synthesised, transcribed back with the ovoscope reference STT, and
scored with word error rate.
"""
import os
import json

import pytest

from ovoscope.tts_intelligibility import score_tts_intelligibility

from ovos_tts_plugin_polly import PollyTTS

LANG = "en-US"
PHRASES = [
    "hello world",
    "what time is it",
    "turn on the kitchen lights",
    "the weather is nice today",
    "set a timer for five minutes",
]


def _has_aws_credentials() -> bool:
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    # boto3 also resolves credentials from profiles / instance metadata
    try:
        import boto3

        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


# Polly is a cloud engine and needs AWS credentials. A missing secret is NOT a
# failure: skip cleanly when no credentials are resolvable.
pytestmark = pytest.mark.skipif(
    not _has_aws_credentials(),
    reason="AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY not set — cloud engine, cannot synthesize in CI",
)


def test_tts_intelligibility():
    tts = PollyTTS()
    report = score_tts_intelligibility(tts, PHRASES, lang=LANG, mode="direct")
    print("::TTS-INTELLIGIBILITY:: " + json.dumps(report.to_dict()))
    assert report.mean_wer <= float(os.environ.get("TTS_MAX_WER", "1.0"))

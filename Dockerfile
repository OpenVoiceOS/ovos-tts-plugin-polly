# Amazon Polly neural/standard voices served through ovos-tts-server's
# ElevenLabs-compatible API. A self-contained image: any client that speaks the
# ovos-tts-server / ElevenLabs API can hit it, and it can be A/B-tested against
# other ovos-tts-server voices by pointing at a different port.
#
# Polly is a CLOUD engine. The image builds with NO credentials baked in, but at
# RUNTIME it needs AWS credentials to synthesize anything. Supply them via a
# mounted mycroft.conf (see README "Docker" section); without them every request
# fails with an AWS auth error. Network access to the AWS Polly endpoint is
# required (this is not an offline/air-gapped voice).
FROM python:3.14-slim

# ffmpeg: the Polly plugin emits mp3; ovos-tts-server transcodes non-WAV plugin
# output to WAV.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# the plugin (pulls boto3 via ".") + the OVOS TTS server. setuptools<81 keeps
# ovos-plugin-manager's pkg_resources usage working. ovos-tts-server>=1.13.5a1
# carries the non-WAV transcode fix (Polly emits mp3); the alpha floor lets pip
# resolve the prerelease without --pre.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "setuptools<81" "." "ovos-tts-server>=1.13.5a1"

# Default voice/engine, overridable with build args. NO credentials are baked in;
# key_id/secret_key must be supplied at runtime via a mounted mycroft.conf.
ARG POLLY_VOICE=Joanna
ARG POLLY_ENGINE=neural
ARG POLLY_REGION=us-east-1
RUN useradd -m -u 1000 ovos \
    && mkdir -p /home/ovos/.config/mycroft \
    && printf '{\n  "tts": {\n    "module": "ovos-tts-plugin-polly",\n    "ovos-tts-plugin-polly": {\n      "voice": "%s",\n      "engine": "%s",\n      "region": "%s"\n    }\n  }\n}\n' "${POLLY_VOICE}" "${POLLY_ENGINE}" "${POLLY_REGION}" \
        > /home/ovos/.config/mycroft/mycroft.conf \
    && chown -R 1000:1000 /home/ovos/.config
USER 1000

EXPOSE 9666
ENTRYPOINT ["ovos-tts-server", "--engine", "ovos-tts-plugin-polly", \
            "--host", "0.0.0.0", "--port", "9666", "--cache"]

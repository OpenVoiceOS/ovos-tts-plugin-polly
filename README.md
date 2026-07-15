# Amazon Polly TTS plugin for OVOS
Requires Amazon access key


Example mycroft.conf config section

```
  "tts": {
    "module": "ovos-tts-plugin-polly",
    "ovos-tts-plugin-polly": {
      "access_key_id": "XXXXXXXXXXXXXXXXX",
      "secret_access_key": "YYYYYYYYYYYYYYYYYYYYYYY",
      "region": "us-east-1",
      "voice": "Matthew",
      "engine": "neural"
    }
  },
```

The plugin reads these config keys: `access_key_id` (alias `key_id`),
`secret_access_key` (alias `secret_key`), `region` (default `us-east-1`),
`voice` (default `Matthew`) and `engine` (`standard` or `neural`, default
`standard`).

## Docker

The image serves Polly behind [`ovos-tts-server`](https://github.com/OpenVoiceOS/ovos-tts-server)
on port `9666` (ElevenLabs-compatible API). It is published to
`ghcr.io/openvoiceos/ovos-tts-plugin-polly`.

Amazon Polly is a **cloud** engine. The image **builds with no credentials**, but
at **runtime it needs AWS credentials** — without them every request fails with an
AWS auth error. The plugin reads credentials from its **config block**, not from
`AWS_*` environment variables, so supply them by mounting a `mycroft.conf`.

Create a `mycroft.conf` (keep it out of git):

```json
{
  "tts": {
    "module": "ovos-tts-plugin-polly",
    "ovos-tts-plugin-polly": {
      "access_key_id": "AKIA...",
      "secret_access_key": "....",
      "region": "us-east-1",
      "voice": "Joanna",
      "engine": "neural"
    }
  }
}
```

Run it:

```bash
docker run --rm -p 9666:9666 \
  -v "$PWD/mycroft.conf:/home/ovos/.config/mycroft/mycroft.conf:ro" \
  ghcr.io/openvoiceos/ovos-tts-plugin-polly:dev
```

or with `docker compose up` (see `docker-compose.yml` — uncomment the `volumes`
mount). The default voice/engine/region are set at build time via the
`POLLY_VOICE` / `POLLY_ENGINE` / `POLLY_REGION` build args, but the `voice` and
`engine` in a mounted `mycroft.conf` override them.

Synthesize with any ElevenLabs/ovos-tts-server client, e.g.:

```bash
curl "http://localhost:9666/synthesize/hello%20world" --output hello.wav
```

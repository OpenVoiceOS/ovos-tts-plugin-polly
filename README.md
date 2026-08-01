# Amazon Polly TTS plugin for OVOS

This plugin lets OpenVoiceOS use Amazon Polly as a text-to-speech engine. It needs an Amazon Web Services access key.

## Install

```bash
pip install ovos-tts-plugin-polly
```

## Usage

Add a `tts` section to `mycroft.conf`:

```json
{
  "tts": {
    "module": "ovos-tts-plugin-polly",
    "ovos-tts-plugin-polly": {
      "access_key_id": "XXXXXXXXXXXXXXXXX",
      "secret_access_key": "YYYYYYYYYYYYYYYYYYYYYYY",
      "region": "us-east-1",
      "voice": "Matthew",
      "engine": "neural"
    }
  }
}
```

The plugin reads these config keys:

- `access_key_id` (alias `key_id`)
- `secret_access_key` (alias `secret_key`)
- `region` (default `us-east-1`)
- `voice` (default `Matthew`)
- `engine`: `standard` or `neural` (default `standard`)

## Docker

The Docker image serves Polly behind [`ovos-tts-server`](https://github.com/OpenVoiceOS/ovos-tts-server) on port `9666`, with an ElevenLabs-compatible API. It is published to `ghcr.io/openvoiceos/ovos-tts-plugin-polly`.

Amazon Polly is a cloud engine. The image builds with no credentials. At runtime it needs AWS credentials. Without them, every request fails with an AWS auth error. The plugin reads credentials from its config block, not from `AWS_*` environment variables. Supply them by mounting a `mycroft.conf`.

Create a `mycroft.conf` and keep it out of git:

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

Run the image:

```bash
docker run --rm -p 9666:9666 \
  -v "$PWD/mycroft.conf:/home/ovos/.config/mycroft/mycroft.conf:ro" \
  ghcr.io/openvoiceos/ovos-tts-plugin-polly:dev
```

You can also use `docker compose up`. See `docker-compose.yml` and uncomment the `volumes` mount. The build args `POLLY_VOICE`, `POLLY_ENGINE`, and `POLLY_REGION` set the default voice, engine, and region at build time. The `voice` and `engine` keys in a mounted `mycroft.conf` override these defaults.

Synthesize speech with any ElevenLabs or `ovos-tts-server` client, for example:

```bash
curl "http://localhost:9666/synthesize/hello%20world" --output hello.wav
```

## Related projects

- [ovos-tts-server](https://github.com/OpenVoiceOS/ovos-tts-server): the TTS server this plugin runs behind in Docker.
- [ovos-plugin-manager](https://github.com/OpenVoiceOS/ovos-plugin-manager): loads and configures this plugin.

## License

Apache-2.0

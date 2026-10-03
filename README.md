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
- `engine`: `standard`, `neural`, `long-form`, or `generative` (default `standard`)

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

## Language and SSML correctness

Requests select voices from the regional, engine-filtered `DescribeVoices` catalog,
including bilingual voices and every result page. Grant `polly:DescribeVoices` in
addition to `polly:SynthesizeSpeech`. Discovery is cached for five minutes.
An explicit incompatible voice fails before synthesis; otherwise the configured
voice is preferred, followed by the alphabetically first compatible voice. Set
`voices` to a language-to-voice mapping (for example `{"fr-CA": "Gabrielle"}`)
to choose deterministic defaults. `lang` is forwarded as `LanguageCode`.

Standard AWS SSML is preserved. Legacy `<whispered>...</whispered>` is translated
only at tag boundaries. SSML fragments are wrapped in `<speak>`. Tag support
varies by engine; AWS remains authoritative for unsupported SSML errors.

Run credential-free regression tests with `pip install -e . pytest pytest-asyncio`
and `pytest -q`.

## Audio and pronunciation controls

- `output_format`: `mp3` (default), `ogg_vorbis`, `ogg_opus`, `pcm`, `mulaw`, or `alaw`.
  PCM is saved as a mono 16-bit WAV so file playback has sample-rate metadata.
  Mu-law/A-law remain raw telephony data and require a compatible player.
- `sample_rate`: a Polly-supported rate for the format (string or integer).
  Defaults: standard MP3/Vorbis 22050; other engines 24000; PCM 16000;
  Opus 48000; mu-law/A-law 8000. Increasing the rate does not improve pronunciation.
- `lexicon_names`: up to five existing pronunciation lexicons in the selected AWS
  region. Polly applies only those matching the selected voice's language.

`get_speech_marks(text, lang=None, voice=None, mark_types=("sentence", "word", "viseme"))`
returns timing dictionaries using a separate billable request. Only standard and
neural engines support these marks. They are not substituted for OVOS phoneme data.
Cache namespaces include region, engine, format, sample rate, and lexicon names.
After updating an existing lexicon's contents, clear the corresponding audio cache.
Language selection follows request language, then the active OVOS session, then
plugin `lang`, and finally the global OVOS locale. An omitted or null request
language allows these defaults; it does not force English.

A configured `preloaded_cache` is a root directory. Polly stores audio in a hashed
subdirectory for each voice, language, region, engine, format, sample rate, and
lexicon selection. Separate roots also use separate in-memory caches. Existing
flat cache files are not automatically reused because their synthesis settings
cannot be verified; matching new contexts reuse their own files across restarts.

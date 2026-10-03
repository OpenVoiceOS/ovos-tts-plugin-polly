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

Amazon Polly is a cloud engine. The image builds with no credentials. At runtime it needs AWS credentials. Without them, every request fails with an AWS auth error. Use the standard AWS credential provider chain, or supply explicit credentials in a mounted `mycroft.conf`.

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

## Streaming and transport

Set `enable_streaming: true` to use OVOS streaming playback. The plugin implements
`StreamingTTS` and yields audio as it arrives; `get_tts()` remains synchronous for
existing callers. Install `ffplay` for MP3/Ogg/Opus streaming, or provide compatible
OVOS playback callbacks. PCM streaming includes a WAV header. Mu-law/A-law need
callbacks configured with their raw format and 8000 Hz rate.

Both paths use bounded reads, close response bodies, and publish files atomically.
Interrupted downloads do not replace a completed audio file. Streaming file output
repairs WAV lengths and registers completed OVOS cache files. Network operations run
in worker threads; audio chunks are consumed with backpressure. No automatic retry
replays a partially spoken response.

Transport settings: `connect_timeout` (5 seconds), `read_timeout` (30 seconds),
`max_attempts` (3 total SDK attempts), `max_pool_connections` (10), and `chunk_size`
(4096 bytes; allowed 256–1048576). TCP keepalive is enabled. Measure your workload
before adjusting these values; larger pools do not raise AWS service quotas.

Without explicit keys the normal AWS credential provider chain is used, including
environment variables and workload roles. Optional `profile_name` and `session_token`
are supported. Never put credentials in committed configuration files.

## Optional bidirectional text/audio streaming

AWS's Python SDK does not support `StartSpeechSynthesisStream`. The optional local
Node.js helper uses the official JavaScript SDK and HTTP/2. It requires Node 22+
and installation of its pinned dependencies:

```bash
cd "$(python -c 'import pathlib, ovos_tts_plugin_polly; print(pathlib.Path(ovos_tts_plugin_polly.__file__).parent / "bridge")')"
npm ci --ignore-scripts
```

Configure `engine: generative` and a voice available in your region. Grant
`polly:StartSpeechSynthesisStream` as well as the discovery permission. Consume
`tts.stream_text(async_text_chunks, lang="en-US")` as an async iterator of audio
bytes. Each input item is a nonempty plain-text string; preserve spaces between
chunks. Audio arrives concurrently with input. PCM output here is raw 16-bit mono,
whereas `stream_tts()` wraps it in WAV. No speech marks or audio caching are applied
to incremental text sessions. This API is for applications supplying incremental
text; the regular OVOS speech path uses `stream_tts()`.

The helper uses a fresh credential snapshot from the Python AWS session for each
stream, including refreshed role/session tokens. Credentials are passed privately
through the child environment; profile selectors and stale tokens are removed so
Node cannot select a different AWS identity. Existing streams retain their signing
credentials until completion; new streams resolve credentials again.
`bidirectional_command` can select an installed helper using an argv list, without
a shell. `bidirectional_timeout` (default 30 seconds) bounds output inactivity and
helper shutdown; tune it for gaps in your text producer. Cancellation stops the
producer and reaps the child. Requests are never automatically replayed.

See [AWS's streaming documentation](https://docs.aws.amazon.com/polly/latest/dg/bidirectional-streaming.html)
for engine/region availability. The helper is tested with simulated SDK event streams;
real AWS interoperability and audible latency must be measured in your environment.
Language selection follows request language, then the active OVOS session, then
plugin `lang`, and finally the global OVOS locale. An omitted or null request
language allows these defaults; it does not force English.

A configured `preloaded_cache` is a root directory. Polly stores audio in a hashed
subdirectory for each voice, language, region, engine, format, sample rate, and
lexicon selection. Separate roots also use separate in-memory caches. Existing
flat cache files are not automatically reused because their synthesis settings
cannot be verified; matching new contexts reuse their own files across restarts.

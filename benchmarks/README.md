# Measuring Polly changes

Install the plugin and run the safe, simulated pipeline first:

```bash
python benchmarks/run.py --repeat 2 --concurrency 4 --output /tmp/polly-simulated.json
```

To make billable requests with your normal AWS credentials:

```bash
python benchmarks/run.py --live --config /path/to/plugin-config.json \
  --repeat 10 --concurrency 1 --samples /tmp/polly-listening \
  --output /tmp/polly-live.json
```

The configuration file contains the plugin block, not the outer `tts` object.
A neural engine with `voices: {"en-US": "Matthew", "fr-CA": "Gabrielle"}` is a useful
starting configuration for the included corpus. Region, voice, and engine availability
must match. Test standard/neural/generative separately; more natural speech is not
necessarily more faithful reading. Exclude unsupported languages from your corpus.

The report separates one cold request, uncached file completion, first streamed
audio byte, full streaming completion, OVOS cache misses, and warm cache hits.
Uncached modes run at the requested concurrency; cache phases are serial.
Percentiles use nearest rank and exclude failures, which are counted separately.
The cold measurement includes lazy voice discovery but excludes plugin construction.
Use enough repeats for meaningful p95 results. Repeat with concurrency 1, 4, and 8,
keeping region, host, network, corpus, sample rate, and engine fixed. Compare revisions
with matching configuration; do not interpret simulated numbers as AWS performance.

`--samples` keeps numbered audio files from uncached requests: index modulo corpus
length identifies the phrase. Later uncached repeats replace those same indices only
when rerunning the command. Stream measurements do not save additional audio files.
Reports include no configuration secrets or request text. Keep generated audio and
reports outside Git. Lexicon changes require clearing audio caches before comparisons.

First audio byte is not first audible sound. For end-to-end latency, capture the
request timestamp and loopback audio from the actual OVOS playback device; report the
first non-silent sample delay separately, including player startup and buffering.
`peak_python_bytes` measures Python allocations during the entire benchmark, including
measurement overhead, not total RSS or per-request memory. Inspect process RSS under
sustained load separately.

Listen to the English and Canadian French recordings using a worksheet with columns:
phrase ID, chosen voice/engine, omitted/added words, numbers/dates/IP fidelity,
name/acronym pronunciation, intelligibility (1–5), naturalness (1–5), and notes.
Have fluent speakers review both languages. Spellings of brand names and acronyms may
have several acceptable pronunciations; define the intended pronunciation before
scoring. Compare custom lexicons and `<phoneme>` SSML on problem phrases. Listening
scores and real AWS latency are deliberately not invented by this harness.

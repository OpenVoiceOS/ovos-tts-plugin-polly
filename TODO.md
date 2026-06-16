# TODO

## Open issues
- [ ] #12 Dependency Dashboard (renovate bot)

## Gaps
- [ ] No test suite (no `tests/` dir, no test config).
- [ ] No README.md.
- [ ] No `pyproject.toml` (legacy `setup.py` packaging only).
- [ ] Missing standard gh-automations CI: no `build-tests`, `coverage`, or `license-check` workflows.
- [ ] Workflows point at `TigreGotico/gh-automations/...@master` instead of `OpenVoiceOS/gh-automations@dev`.
- [ ] Committed scratch artifact: `ovos_tts_plugin_polly.egg-info/`.
- [ ] `PollyTTSPluginConfig`: `hi-IN` and some `en-IN` entries have wrong `lang` value; `en-IN` lists `Raveena` three times.

## Code TODOs
- [ ] `ovos_tts_plugin_polly/__init__.py:61` — validate that selected voice matches the lang.
- [ ] `ovos_tts_plugin_polly/__init__.py:63` — get default voice for lang.

# ovos-tts-plugin-polly

OVOS TTS plugin wrapping Amazon Polly cloud speech synthesis via `boto3`.

## Setup
```bash
pip install -e .
```
Requires AWS credentials (access key id + secret) supplied through plugin config. Runtime deps: `boto3`, `ovos-plugin-manager`.

## Test
No test suite exists. The only runnable check is the `__main__` block in `ovos_tts_plugin_polly/__init__.py`, which performs a live Polly synthesis call (needs valid AWS credentials and network).

## Lint/Typecheck
Not configured.

## Layout
- `ovos_tts_plugin_polly/__init__.py` — everything: `PollyTTS` (extends `ovos_plugin_manager.templates.tts.TTS`), `PollyTTSValidator`, and the `PollyTTSPluginConfig` dict of supported languages/voices.
- `ovos_tts_plugin_polly/version.py` — semver components (auto-managed).
- `setup.py` — packaging; reads version from `version.py`.

Entry-point group: `mycroft.plugin.tts` -> `ovos-tts-plugin-polly = ovos_tts_plugin_polly:PollyTTS`; config sample under `mycroft.plugin.tts.config`.

Config keys: `voice` (default `Matthew`), `key_id`/`access_key_id`, `secret_key`/`secret_access_key`, `region` (default `us-east-1`), `engine` (default `standard`). SSML is detected and Polly-specific `amazon:effect` substitutions are applied; output is mp3.

## Conventions (Org hard rules)
- Branches: `dev` (work) / `master` (stable). NEVER `main`.
- Never edit `version.py`; gh-automations bumps semver from conventional-commit prefixes (`feat:`/`fix:`/`feat!:`).
- New repos private by default.
- Commit identity: JarbasAi <jarbasai@mailfence.com>.
- Reference `OpenVoiceOS/gh-automations` reusable workflows at `@dev`.
- No Neon / `neon-*` references.
- No meta-commentary (no history, no dates).
- CI is provided by OpenVoiceOS/gh-automations reusable workflows.

## Gotchas
- Existing workflows reference `TigreGotico/gh-automations/...@master` rather than `OpenVoiceOS/gh-automations@dev` — non-standard versus org convention.
- `setup.py`-based packaging (no `pyproject.toml`).
- `ovos_tts_plugin_polly.egg-info/` is committed scratch and should not be tracked.
- `PollyTTSPluginConfig` data quirks: the `hi-IN` and several `en-IN` voice entries carry `lang: "en-IN"` rather than their map key; `en-IN` has three identical `Raveena` entries.
- `available_languages` derives from `PollyTTSPluginConfig.keys()`, so it advertises the static map, not what the AWS account/region actually permits.
- No retry/error handling around `synthesize_speech`; AWS errors propagate raw.

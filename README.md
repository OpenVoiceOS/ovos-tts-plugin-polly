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

import boto3
import logging
from ovos_plugin_manager.templates.tts import TTS, TTSValidator
from ovos_utils import classproperty

logging.getLogger("botocore").setLevel(logging.CRITICAL)
logging.getLogger("boto3").setLevel(logging.CRITICAL)
logging.getLogger("urllib3.util.retry").setLevel(logging.CRITICAL)


class PollyTTS(TTS):
    def __init__(self, *args, **kwargs):
        ssml_tags = [
            "speak",
            "say-as",
            "voice",
            "prosody",
            "break",
            "emphasis",
            "sub",
            "lang",
            "phoneme",
            "w",
            "whisper",
            "amazon:auto-breaths",
            "p",
            "s",
            "amazon:effect",
            "mark",
        ]
        super().__init__(
            *args,
            **kwargs,
            audio_ext="mp3",
            ssml_tags=ssml_tags,
            validator=PollyTTSValidator(self),
        )
        # Catch Chinese alt code
        if self.lang.lower() == "zh-zh":
            self.lang = "cmn-cn"

        self.voice = self.config.get("voice", "Matthew")
        self.key_id = (
                self.config.get("key_id") or self.config.get("access_key_id") or ""
        )
        self.key = (
                self.config.get("secret_key") or self.config.get("secret_access_key") or ""
        )
        self.region = self.config.get("region", "us-east-1")
        self.engine = self.config.get("engine", "standard")
        self.polly = boto3.Session(
            aws_access_key_id=self.key_id,
            aws_secret_access_key=self.key,
            region_name=self.region,
        ).client("polly")

    def get_tts(self, sentence, wav_file, lang=None, voice=None):
        if lang:
            if voice:
                pass
                # TODO - validate that selected voice matches the lang
            else:
                # TODO - get default voice for lang
                pass
        voice = voice or self.voice
        text_type = "text"
        if self.remove_ssml(sentence) != sentence:
            text_type = "ssml"
            sentence = (
                sentence.replace("\whispered", "/amazon:effect")
                .replace("\\whispered", "/amazon:effect")
                .replace("whispered", 'amazon:effect name="whispered"')
            )
        response = self.polly.synthesize_speech(
            OutputFormat=self.audio_ext,
            Text=sentence,
            Engine=self.engine,
            TextType=text_type,
            VoiceId=voice.title(),
        )

        with open(wav_file, "wb") as f:
            f.write(response["AudioStream"].read())
        return wav_file, None

    def describe_voices(self, language_code="en-US"):
        if language_code.islower():
            a, b = language_code.split("-")
            b = b.upper()
            language_code = "-".join([a, b])
        # example 'it-IT' useful to retrieve voices
        voices = self.polly.describe_voices(LanguageCode=language_code)

        return voices

    @classproperty
    def available_languages(cls) -> set:
        """Return languages supported by this TTS implementation in this state
        This property should be overridden by the derived class to advertise
        what languages that engine supports.
        Returns:
            set: supported languages
        """
        return set(PollyTTSPluginConfig.keys())


class PollyTTSValidator(TTSValidator):
    def __init__(self, tts):
        super(PollyTTSValidator, self).__init__(tts)

    def validate_lang(self):
        langs = [l.lower() for l in PollyTTSPluginConfig.keys()]
        assert self.tts.lang.lower() in langs

    def validate_dependencies(self):
        try:
            from boto3 import Session
        except ImportError as exc:
            raise ImportError(
                "PollyTTS dependencies not installed, please run pip install boto3"
            ) from exc

    def get_tts_class(self):
        return PollyTTS


PollyTTSPluginConfig = {
    "en-US": [
        {
            "voice": "Kevin",
            "lang": "en-US",
            "meta": {
                "display_name": "Kevin",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Salli",
            "lang": "en-US",
            "meta": {
                "display_name": "Salli",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Matthew",
            "lang": "en-US",
            "meta": {
                "display_name": "Matthew",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Kimberly",
            "lang": "en-US",
            "meta": {
                "display_name": "Kimberly",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Kendra",
            "lang": "en-US",
            "meta": {
                "display_name": "Kendra",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Justin",
            "lang": "en-US",
            "meta": {
                "display_name": "Justin",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Joey",
            "lang": "en-US",
            "meta": {
                "display_name": "Joey",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Joanna",
            "lang": "en-US",
            "meta": {
                "display_name": "Joanna",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Danielle",
            "lang": "en-US",
            "meta": {
                "display_name": "Danielle",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Ivy",
            "lang": "en-US",
            "meta": {
                "display_name": "Ivy",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Ruth",
            "lang": "en-US",
            "meta": {
                "display_name": "Ruth",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Gregory",
            "lang": "en-US",
            "meta": {
                "display_name": "Gregory",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Stephen",
            "lang": "en-US",
            "meta": {
                "display_name": "Stephen",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "tr-TR": [
        {
            "voice": "Filiz",
            "lang": "tr-TR",
            "meta": {
                "display_name": "Filiz",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "sv-SE": [
        {
            "voice": "Astrid",
            "lang": "sv-SE",
            "meta": {
                "display_name": "Astrid",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "ru-RU": [
        {
            "voice": "Tatyana",
            "lang": "ru-RU",
            "meta": {
                "display_name": "Tatyana",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Maxim",
            "lang": "ru-RU",
            "meta": {
                "display_name": "Maxim",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "ro-RO": [
        {
            "voice": "Carmen",
            "lang": "ro-RO",
            "meta": {
                "display_name": "Carmen",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "pt-PT": [
        {
            "voice": "Ines",
            "lang": "pt-PT",
            "meta": {
                "display_name": "Ines",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Cristiano",
            "lang": "pt-PT",
            "meta": {
                "display_name": "Cristiano",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "pt-BR": [
        {
            "voice": "Vitoria",
            "lang": "pt-BR",
            "meta": {
                "display_name": "Vitoria",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Ricardo",
            "lang": "pt-BR",
            "meta": {
                "display_name": "Ricardo",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Camila",
            "lang": "pt-BR",
            "meta": {
                "display_name": "Camila",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "pl-PL": [
        {
            "voice": "Maja",
            "lang": "pl-PL",
            "meta": {
                "display_name": "Maja",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Jan",
            "lang": "pl-PL",
            "meta": {
                "display_name": "Jan",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Jacek",
            "lang": "pl-PL",
            "meta": {
                "display_name": "Jacek",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Ewa",
            "lang": "pl-PL",
            "meta": {
                "display_name": "Ewa",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "nl-NL": [
        {
            "voice": "Ruben",
            "lang": "nl-NL",
            "meta": {
                "display_name": "Ruben",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Lotte",
            "lang": "nl-NL",
            "meta": {
                "display_name": "Lotte",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "nb-NO": [
        {
            "voice": "Liv",
            "lang": "nb-NO",
            "meta": {
                "display_name": "Liv",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "ko-KR": [
        {
            "voice": "Seoyeon",
            "lang": "ko-KR",
            "meta": {
                "display_name": "Seoyeon",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "ja-JP": [
        {
            "voice": "Takumi",
            "lang": "ja-JP",
            "meta": {
                "display_name": "Takumi",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Mizuki",
            "lang": "ja-JP",
            "meta": {
                "display_name": "Mizuki",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "it-IT": [
        {
            "voice": "Bianca",
            "lang": "it-IT",
            "meta": {
                "display_name": "Bianca",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Giorgio",
            "lang": "it-IT",
            "meta": {
                "display_name": "Giorgio",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Carla",
            "lang": "it-IT",
            "meta": {
                "display_name": "Carla",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "is-IS": [
        {
            "voice": "Karl",
            "lang": "is-IS",
            "meta": {
                "display_name": "Karl",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Dora",
            "lang": "is-IS",
            "meta": {
                "display_name": "Dora",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "fr-FR": [
        {
            "voice": "Mathieu",
            "lang": "fr-FR",
            "meta": {
                "display_name": "Mathieu",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Lea",
            "lang": "fr-FR",
            "meta": {
                "display_name": "Lea",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Celine",
            "lang": "fr-FR",
            "meta": {
                "display_name": "Celine",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Remi",
            "lang": "fr-FR",
            "meta": {
                "display_name": "Remi",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "fr-CA": [
        {
            "voice": "Chantal",
            "lang": "fr-CA",
            "meta": {
                "display_name": "Chantal",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Gabrielle",
            "lang": "fr-CA",
            "meta": {
                "display_name": "Gabrielle",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Liam",
            "lang": "fr-CA",
            "meta": {
                "display_name": "Liam",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "es-US": [
        {
            "voice": "Penelope",
            "lang": "es-US",
            "meta": {
                "display_name": "Penelope",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Miguel",
            "lang": "es-US",
            "meta": {
                "display_name": "Miguel",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Lupe",
            "lang": "es-US",
            "meta": {
                "display_name": "Lupe",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Pedro",
            "lang": "es-US",
            "meta": {
                "display_name": "Pedro",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "es-MX": [
        {
            "voice": "Mia",
            "lang": "es-MX",
            "meta": {
                "display_name": "Mia",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "es-ES": [
        {
            "voice": "Lucia",
            "lang": "es-ES",
            "meta": {
                "display_name": "Lucia",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Enrique",
            "lang": "es-ES",
            "meta": {
                "display_name": "Enrique",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Conchita",
            "lang": "es-ES",
            "meta": {
                "display_name": "Conchita",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "en-GB-WLS": [
        {
            "voice": "Geraint",
            "lang": "en-GB-WLS",
            "meta": {
                "display_name": "Geraint",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        }
    ],
    "en-NZ": [
        {
            "voice": "Aria",
            "lang": "en-NZ",
            "meta": {
                "display_name": "Aria",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "en-ZA": [
        {
            "voice": "Ayanda",
            "lang": "en-ZA",
            "meta": {
                "display_name": "Ayanda",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "en-IN": [
        {
            "voice": "Raveena",
            "lang": "en-IN",
            "meta": {
                "display_name": "Raveena",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Raveena",
            "lang": "en-IN",
            "meta": {
                "display_name": "Raveena",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Raveena",
            "lang": "en-IN",
            "meta": {
                "display_name": "Raveena",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "hi-IN": [
        {
            "voice": "Aditi",
            "lang": "en-IN",
            "meta": {
                "display_name": "Aditi",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Kajal",
            "lang": "en-IN",
            "meta": {
                "display_name": "Kajal",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Raveena",
            "lang": "en-IN",
            "meta": {
                "display_name": "Raveena",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "en-GB": [
        {
            "voice": "Emma",
            "lang": "en-GB",
            "meta": {
                "display_name": "Emma",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Brian",
            "lang": "en-GB",
            "meta": {
                "display_name": "Brian",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Amy",
            "lang": "en-GB",
            "meta": {
                "display_name": "Amy",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Arthur",
            "lang": "en-GB",
            "meta": {
                "display_name": "Arthur",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "en-AU": [
        {
            "voice": "Russell",
            "lang": "en-AU",
            "meta": {
                "display_name": "Russell",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Nicole",
            "lang": "en-AU",
            "meta": {
                "display_name": "Nicole",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Olivia",
            "lang": "en-AU",
            "meta": {
                "display_name": "Olivia",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
    ],
    "de-DE": [
        {
            "voice": "Vicki",
            "lang": "de-DE",
            "meta": {
                "display_name": "Vicki",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Marlene",
            "lang": "de-DE",
            "meta": {
                "display_name": "Marlene",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Hans",
            "lang": "de-DE",
            "meta": {
                "display_name": "Hans",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
        {
            "voice": "Daniel",
            "lang": "de-DE",
            "meta": {
                "display_name": "Daniel",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "da-DK": [
        {
            "voice": "Naja",
            "lang": "da-DK",
            "meta": {
                "display_name": "Naja",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        },
        {
            "voice": "Mads",
            "lang": "da-DK",
            "meta": {
                "display_name": "Mads",
                "offline": False,
                "gender": "male",
                "priority": 40,
            },
        },
    ],
    "cy-GB": [
        {
            "voice": "Gwyneth",
            "lang": "cy-GB",
            "meta": {
                "display_name": "Gwyneth",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "cmn-CN": [
        {
            "voice": "Zhiyu",
            "lang": "cmn-CN",
            "meta": {
                "display_name": "Zhiyu",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "arb": [
        {
            "voice": "Zeina",
            "lang": "arb",
            "meta": {
                "display_name": "Zeina",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "ca-ES": [
        {
            "voice": "Arlet",
            "lang": "ca-ES",
            "meta": {
                "display_name": "Arlet",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
    "de-AT": [
        {
            "voice": "Hannah",
            "lang": "de-AT",
            "meta": {
                "display_name": "Hannah",
                "offline": False,
                "gender": "female",
                "priority": 40,
            },
        }
    ],
}

if __name__ == "__main__":
    e = PollyTTS(config={"key_id": "", "secret_key": ""})

    SSML = """<speak>
    This is my original voice, without any modifications. <amazon:effect vocal-tract-length="+15%">ss
    Now, imagine that I am much bigger. </amazon:effect> <amazon:effect vocal-tract-length="-15%">
    Or, perhaps you prefer my voice when I'm very small. </amazon:effect> You can also control the
    timbre of my voice by making minor adjustments. <amazon:effect vocal-tract-length="+10%">
    For example, by making me sound just a little bigger. </amazon:effect><amazon:effect
    vocal-tract-length="-10%"> Or, making me sound only somewhat smaller. </amazon:effect>
    </speak>"""
    e.get_tts(SSML, "polly.mp3")

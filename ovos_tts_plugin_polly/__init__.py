import logging

import boto3
from ovos_plugin_manager.templates.tts import TTS, TTSValidator

logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('urllib3.util.retry').setLevel(logging.CRITICAL)


class PollyTTS(TTS):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, audio_ext="mp3",
                         ssml_tags=["speak", "say-as", "voice",
                                    "prosody", "break",
                                    "emphasis", "sub", "lang",
                                    "phoneme", "w", "whisper",
                                    "amazon:auto-breaths",
                                    "p", "s", "amazon:effect",
                                    "mark"],
                         validator=PollyTTSValidator(self))
        # Catch Chinese alt code
        if self.lang.lower() == "zh-zh":
            self.lang = "cmn-cn"

        self.voice = self.config.get("voice", "Matthew")
        self.key_id = self.config.get("key_id") or \
                      self.config.get("access_key_id") or ""
        self.key = self.config.get("secret_key") or \
                   self.config.get("secret_access_key") or ""
        self.region = self.config.get("region", 'us-east-1')
        self.polly = boto3.Session(aws_access_key_id=self.key_id,
                                   aws_secret_access_key=self.key,
                                   region_name=self.region).client('polly')

    def get_tts(self, sentence, wav_file):
        text_type = "text"
        if self.remove_ssml(sentence) != sentence:
            text_type = "ssml"
            sentence = sentence.replace("\whispered", "/amazon:effect") \
                .replace("\\whispered", "/amazon:effect") \
                .replace("whispered", "amazon:effect name=\"whispered\"")
        response = self.polly.synthesize_speech(
            OutputFormat=self.audio_ext,
            Text=sentence,
            TextType=text_type,
            VoiceId=self.voice.title())

        with open(wav_file, 'wb') as f:
            f.write(response['AudioStream'].read())
        return wav_file, None

    def describe_voices(self, language_code="en-US"):
        if language_code.islower():
            a, b = language_code.split("-")
            b = b.upper()
            language_code = "-".join([a, b])
        # example 'it-IT' useful to retrieve voices
        voices = self.polly.describe_voices(LanguageCode=language_code)

        return voices


class PollyTTSValidator(TTSValidator):
    def __init__(self, tts):
        super(PollyTTSValidator, self).__init__(tts)

    def validate_lang(self):
        # TODO
        pass

    def validate_dependencies(self):
        try:
            from boto3 import Session
        except ImportError:
            raise Exception(
                'PollyTTS dependencies not installed, please run pip install '
                'boto3 ')

    def validate_connection(self):
        try:
            if not self.tts.voice:
                raise Exception("Polly TTS Voice not configured")
            output = self.tts.describe_voices()
        except TypeError:
            raise Exception(
                'PollyTTS server could not be verified. Please check your '
                'internet connection and credentials.')

    def get_tts_class(self):
        return PollyTTS


PollyTTSPluginConfig = {
    'en-US': [{'display_name': 'Kevin', 'voice': 'Kevin', 'lang': 'en-US', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Salli', 'voice': 'Salli', 'lang': 'en-US', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Matthew', 'voice': 'Matthew', 'lang': 'en-US', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Kimberly', 'voice': 'Kimberly', 'lang': 'en-US', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Kendra', 'voice': 'Kendra', 'lang': 'en-US', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Justin', 'voice': 'Justin', 'lang': 'en-US', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Joey', 'voice': 'Joey', 'lang': 'en-US', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Joanna', 'voice': 'Joanna', 'lang': 'en-US', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Ivy', 'voice': 'Ivy', 'lang': 'en-US', 'offline': False, 'gender': 'female', "priority": 40}],
    'tr-TR': [{'display_name': 'Filiz', 'voice': 'Filiz', 'lang': 'tr-TR', 'offline': False, 'gender': 'female', "priority": 40}],
    'sv-SE': [{'display_name': 'Astrid', 'voice': 'Astrid', 'lang': 'sv-SE', 'offline': False, 'gender': 'female', "priority": 40}],
    'ru-RU': [{'display_name': 'Tatyana', 'voice': 'Tatyana', 'lang': 'ru-RU', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Maxim', 'voice': 'Maxim', 'lang': 'ru-RU', 'offline': False, 'gender': 'male', "priority": 40}],
    'ro-RO': [{'display_name': 'Carmen', 'voice': 'Carmen', 'lang': 'ro-RO', 'offline': False, 'gender': 'female', "priority": 40}],
    'pt-PT': [{'display_name': 'Ines', 'voice': 'Ines', 'lang': 'pt-PT', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Cristiano', 'voice': 'Cristiano', 'lang': 'pt-PT', 'offline': False, 'gender': 'male', "priority": 40}],
    'pt-BR': [{'display_name': 'Vitoria', 'voice': 'Vitoria', 'lang': 'pt-BR', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Ricardo', 'voice': 'Ricardo', 'lang': 'pt-BR', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Camila', 'voice': 'Camila', 'lang': 'pt-BR', 'offline': False, 'gender': 'female', "priority": 40}],
    'pl-PL': [{'display_name': 'Maja', 'voice': 'Maja', 'lang': 'pl-PL', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Jan', 'voice': 'Jan', 'lang': 'pl-PL', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Jacek', 'voice': 'Jacek', 'lang': 'pl-PL', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Ewa', 'voice': 'Ewa', 'lang': 'pl-PL', 'offline': False, 'gender': 'female', "priority": 40}],
    'nl-NL': [{'display_name': 'Ruben', 'voice': 'Ruben', 'lang': 'nl-NL', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Lotte', 'voice': 'Lotte', 'lang': 'nl-NL', 'offline': False, 'gender': 'female', "priority": 40}],
    'nb-NO': [{'display_name': 'Liv', 'voice': 'Liv', 'lang': 'nb-NO', 'offline': False, 'gender': 'female', "priority": 40}],
    'ko-KR': [{'display_name': 'Seoyeon', 'voice': 'Seoyeon', 'lang': 'ko-KR', 'offline': False, 'gender': 'female', "priority": 40}],
    'ja-JP': [{'display_name': 'Takumi', 'voice': 'Takumi', 'lang': 'ja-JP', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Mizuki', 'voice': 'Mizuki', 'lang': 'ja-JP', 'offline': False, 'gender': 'female', "priority": 40}],
    'it-IT': [{'display_name': 'Bianca', 'voice': 'Bianca', 'lang': 'it-IT', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Giorgio', 'voice': 'Giorgio', 'lang': 'it-IT', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Carla', 'voice': 'Carla', 'lang': 'it-IT', 'offline': False, 'gender': 'female', "priority": 40}],
    'is-IS': [{'display_name': 'Karl', 'voice': 'Karl', 'lang': 'is-IS', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Dora', 'voice': 'Dora', 'lang': 'is-IS', 'offline': False, 'gender': 'female', "priority": 40}],
    'fr-FR': [{'display_name': 'Mathieu', 'voice': 'Mathieu', 'lang': 'fr-FR', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Lea', 'voice': 'Lea', 'lang': 'fr-FR', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Celine', 'voice': 'Celine', 'lang': 'fr-FR', 'offline': False, 'gender': 'female', "priority": 40}],
    'fr-CA': [{'display_name': 'Chantal', 'voice': 'Chantal', 'lang': 'fr-CA', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Gabrielle', 'voice': 'Gabrielle', 'lang': 'fr-CA', 'offline': False,
               'gender': 'female', "priority": 40},
              {'display_name': 'Liam', 'voice': 'Liam', 'lang': 'fr-CA', 'offline': False, 'gender': 'male', "priority": 40}],
    'es-US': [{'display_name': 'Penelope', 'voice': 'Penelope', 'lang': 'es-US', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Miguel', 'voice': 'Miguel', 'lang': 'es-US', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Lupe', 'voice': 'Lupe', 'lang': 'es-US', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Pedro', 'voice': 'Pedro', 'lang': 'es-US', 'offline': False, 'gender': 'male', "priority": 40}],
    'es-MX': [{'display_name': 'Mia', 'voice': 'Mia', 'lang': 'es-MX', 'offline': False, 'gender': 'female', "priority": 40}],
    'es-ES': [{'display_name': 'Lucia', 'voice': 'Lucia', 'lang': 'es-ES', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Enrique', 'voice': 'Enrique', 'lang': 'es-ES', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Conchita', 'voice': 'Conchita', 'lang': 'es-ES', 'offline': False, 'gender': 'female', "priority": 40}],
    'en-GB-WLS': [
        {'display_name': 'Geraint', 'voice': 'Geraint', 'lang': 'en-GB-WLS', 'offline': False, 'gender': 'male', "priority": 40}],
    'en-NZ': [{'display_name': 'Aria', 'voice': 'Aria', 'lang': 'en-NZ', 'offline': False, 'gender': 'female', "priority": 40}],
    'en-ZA': [{'display_name': 'Ayanda', 'voice': 'Ayanda', 'lang': 'en-ZA', 'offline': False, 'gender': 'female', "priority": 40}],
    'en-IN': [{'display_name': 'Raveena', 'voice': 'Raveena', 'lang': 'en-IN', 'offline': False, 'gender': 'female', "priority": 40}],
    'hi-IN': [{'display_name': 'Aditi', 'voice': 'Aditi', 'lang': 'en-IN', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Kajal', 'voice': 'Kajal', 'lang': 'en-IN', 'offline': False, 'gender': 'female', "priority": 40}],
    'en-GB': [{'display_name': 'Emma', 'voice': 'Emma', 'lang': 'en-GB', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Brian', 'voice': 'Brian', 'lang': 'en-GB', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Amy', 'voice': 'Amy', 'lang': 'en-GB', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Arthur', 'voice': 'Arthur', 'lang': 'en-GB', 'offline': False, 'gender': 'male', "priority": 40}],
    'en-AU': [{'display_name': 'Russell', 'voice': 'Russell', 'lang': 'en-AU', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Nicole', 'voice': 'Nicole', 'lang': 'en-AU', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Olivia', 'voice': 'Olivia', 'lang': 'en-AU', 'offline': False, 'gender': 'female', "priority": 40}],
    'de-DE': [{'display_name': 'Vicki', 'voice': 'Vicki', 'lang': 'de-DE', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Marlene', 'voice': 'Marlene', 'lang': 'de-DE', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Hans', 'voice': 'Hans', 'lang': 'de-DE', 'offline': False, 'gender': 'male', "priority": 40},
              {'display_name': 'Daniel', 'voice': 'Daniel', 'lang': 'de-DE', 'offline': False, 'gender': 'male', "priority": 40}],
    'da-DK': [{'display_name': 'Naja', 'voice': 'Naja', 'lang': 'da-DK', 'offline': False, 'gender': 'female', "priority": 40},
              {'display_name': 'Mads', 'voice': 'Mads', 'lang': 'da-DK', 'offline': False, 'gender': 'male', "priority": 40}],
    'cy-GB': [{'display_name': 'Gwyneth', 'voice': 'Gwyneth', 'lang': 'cy-GB', 'offline': False, 'gender': 'female', "priority": 40}],
    'cmn-CN': [{'display_name': 'Zhiyu', 'voice': 'Zhiyu', 'lang': 'cmn-CN', 'offline': False, 'gender': 'female', "priority": 40}],
    'arb': [{'display_name': 'Zeina', 'voice': 'Zeina', 'lang': 'arb', 'offline': False, 'gender': 'female', "priority": 40}],
    'ca-ES': [{'display_name': 'Arlet', 'voice': 'Arlet', 'lang': 'ca-ES', 'offline': False, 'gender': 'female', "priority": 40}],
    'de-AT': [{'display_name': 'Hannah', 'voice': 'Hannah', 'lang': 'de-AT', 'offline': False, 'gender': 'female', "priority": 40}]}


if __name__ == "__main__":
    e = PollyTTS(config={"key_id": "",
                         "secret_key": ""})

    ssml = """<speak>
     This is my original voice, without any modifications. <amazon:effect vocal-tract-length="+15%"> 
     Now, imagine that I am much bigger. </amazon:effect> <amazon:effect vocal-tract-length="-15%"> 
     Or, perhaps you prefer my voice when I'm very small. </amazon:effect> You can also control the 
     timbre of my voice by making minor adjustments. <amazon:effect vocal-tract-length="+10%"> 
     For example, by making me sound just a little bigger. </amazon:effect><amazon:effect 
     vocal-tract-length="-10%"> Or, making me sound only somewhat smaller. </amazon:effect> 
</speak>"""
    e.get_tts(ssml, "polly.mp3")

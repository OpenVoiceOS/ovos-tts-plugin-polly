import asyncio
import copy
import hashlib
import json
import os
import re
import struct
import tempfile
import threading
import time
import wave
from contextlib import closing, suppress
from pathlib import Path

import boto3
from botocore.config import Config
from ovos_plugin_manager.templates.tts import StreamingTTS, TTSContext, TTSValidator
from ovos_plugin_manager.utils.tts_cache import AudioFile, hash_sentence
from ovos_utils import classproperty
from ovos_utils.lang import standardize_lang_tag


class PollyTTSContext(TTSContext):
    """Keep custom persistent cache roots isolated by the synthesis context."""

    def __init__(self, *, cache_config, **kwargs):
        """Retain the plugin cache options for callers using the context directly."""
        super().__init__(**kwargs)
        self._cache_config = dict(cache_config)

    def get_cache(self, audio_ext="wav", cache_config=None):
        """Scope custom cache roots without modifying the caller's configuration."""
        config = dict(self._cache_config if cache_config is None else cache_config)
        root = config.get("preloaded_cache")
        if root:
            namespace = hashlib.sha256(self.tts_id.encode()).hexdigest()
            config["preloaded_cache"] = os.path.join(
                os.path.abspath(os.path.expanduser(str(root))), namespace)
        return super().get_cache(audio_ext, config)



class PollyTTS(StreamingTTS):
    """Adapt Amazon Polly synthesis and voice discovery to the OVOS TTS contract."""
    def __init__(self, *args, **kwargs):
        """Initialize the OVOS adapter and a reusable regional Polly client."""
        self._active_streams = {}
        self._streams_lock = threading.Lock()
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
            "amazon:domain",
            "whispered",
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
        if self.engine not in {"standard", "neural", "long-form", "generative"}:
            raise ValueError(f"Unsupported Polly engine: {self.engine}")
        self.output_format = self.config.get("output_format", "mp3")
        extensions = {"mp3": "mp3", "ogg_vorbis": "ogg", "ogg_opus": "opus",
                      "pcm": "wav", "mulaw": "ul", "alaw": "al"}
        if self.output_format not in extensions:
            raise ValueError(f"Unsupported audio output_format: {self.output_format}")
        self.audio_ext = extensions[self.output_format]
        self.sample_rate = str(self.config.get("sample_rate") or (
            "16000" if self.output_format == "pcm" else
            "48000" if self.output_format == "ogg_opus" else
            "8000" if self.output_format in {"mulaw", "alaw"} else
            "22050" if self.engine == "standard" else "24000"))
        valid_rates = ({"8000", "16000"} if self.output_format == "pcm" else
                       {"48000"} if self.output_format == "ogg_opus" else
                       {"8000"} if self.output_format in {"mulaw", "alaw"} else
                       {"8000", "16000", "22050", "24000", "44100", "48000"})
        if self.sample_rate not in valid_rates:
            raise ValueError(f"Invalid sample_rate for {self.output_format}")
        self.lexicon_names = self.config.get("lexicon_names", [])
        if (not isinstance(self.lexicon_names, list) or len(self.lexicon_names) > 5
                or any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9]{1,20}", n)
                       for n in self.lexicon_names)):
            raise ValueError("lexicon_names must contain at most five Polly lexicon names")
        self._voices_cache = {}
        self._voices_lock = threading.Lock()
        session_kwargs = {"region_name": self.region}
        if bool(self.key_id) != bool(self.key):
            raise ValueError("Provide both AWS access key ID and secret key")
        if self.key_id:
            session_kwargs.update(aws_access_key_id=self.key_id,
                                  aws_secret_access_key=self.key)
            if self.config.get("session_token"):
                session_kwargs["aws_session_token"] = self.config["session_token"]
        if self.config.get("profile_name"):
            session_kwargs["profile_name"] = self.config["profile_name"]
        self.chunk_size = int(self.config.get("chunk_size", 4096))
        if not 256 <= self.chunk_size <= 1048576:
            raise ValueError("chunk_size must be between 256 and 1048576 bytes")
        self.aws_session = boto3.Session(**session_kwargs)
        self.polly = self.aws_session.client("polly", config=Config(
            connect_timeout=float(self.config.get("connect_timeout", 5)),
            read_timeout=float(self.config.get("read_timeout", 30)),
            max_pool_connections=int(self.config.get("max_pool_connections", 10)),
            tcp_keepalive=True,
            retries={"mode": "standard", "total_max_attempts":
                     int(self.config.get("max_attempts", 3))}))

    @staticmethod
    def _language_code(lang):
        """Normalize OVOS language aliases and casing for the Polly API."""
        if not lang:
            return None
        aliases = {"zh-zh": "cmn-CN", "zh-cn": "cmn-CN"}
        lang = lang.replace("_", "-")
        if lang.lower() in aliases:
            return aliases[lang.lower()]
        parts = lang.split("-")
        return "-".join([parts[0].lower()] + [p.upper() for p in parts[1:]])

    def describe_voices(self, language_code="en-US", engine=None):
        """Return every page, including bilingual voices, for this region."""
        params = {"Engine": engine or self.engine,
                  "IncludeAdditionalLanguageCodes": True}
        if language_code:
            params["LanguageCode"] = self._language_code(language_code)
        key = tuple(sorted(params.items()))
        with self._voices_lock:
            cached = self._voices_cache.get(key)
            if cached and time.monotonic() - cached[0] < 300:
                return copy.deepcopy(cached[1])
            voices = []
            while True:
                page = self.polly.describe_voices(**params)
                voices.extend(page.get("Voices", []))
                if not page.get("NextToken"):
                    break
                params["NextToken"] = page["NextToken"]
            result = {"Voices": voices}
            self._voices_cache[key] = (time.monotonic(), result)
            return copy.deepcopy(result)

    def _resolve_voice(self, lang=None, voice=None):
        """Select a compatible regional voice or reject an explicit incompatible choice."""
        lang = self._language_code(lang or self.config.get("lang"))
        voices = self.describe_voices(lang)["Voices"]
        requested = voice or self.config.get("voices", {}).get(lang) or self.voice
        match = next((v for v in voices
                      if v["Id"].casefold() == requested.casefold()), None)
        if match:
            return match["Id"], lang
        if voice or not lang or self.config.get("voices", {}).get(lang):
            raise ValueError(f"Voice {requested!r} is unavailable for language "
                             f"{lang!r}, engine {self.engine!r} in {self.region}")
        if not voices:
            raise ValueError(f"No {self.engine} voices for {lang} in {self.region}")
        return sorted(voices, key=lambda v: v["Id"])[0]["Id"], lang

    def _get_ctxt(self, kwargs=None):
        """Resolve the effective voice and language before OVOS chooses an audio cache."""
        request = dict(kwargs or {})
        if not request.get("lang"):
            request.pop("lang", None)
        ctxt = super()._get_ctxt(request)
        # The base context puts request/session language in synth_kwargs, but
        # falls straight back to the global locale when neither is present.
        language = (ctxt.synth_kwargs.get("lang") or
                    self.config.get("lang") or ctxt.lang)
        # OVOS injects the configured voice; distinguish it from a caller override.
        voice, lang = self._resolve_voice(
            language, (kwargs or {}).get("voice"))
        ctxt.lang = standardize_lang_tag(lang)
        ctxt.voice = voice
        ctxt.synth_kwargs.update(voice=voice, lang=lang)
        cache_root = self.config.get("preloaded_cache")
        cache_root = os.path.abspath(os.path.expanduser(str(cache_root))) if cache_root else None
        settings = [self.region, self.engine, self.output_format,
                    self.sample_rate, self.lexicon_names, cache_root]
        fingerprint = hashlib.sha256(json.dumps(settings).encode()).hexdigest()[:16]
        return PollyTTSContext(
            plugin_id=f"{ctxt.plugin_id}/{fingerprint}", lang=ctxt.lang,
            voice=ctxt.voice, synth_kwargs=ctxt.synth_kwargs,
            cache_config=self.config)

    @staticmethod
    def _prepare_text(sentence):
        # Translate only legacy tags, never ordinary words or attribute values.
        """Preserve plain text and AWS SSML while translating legacy whisper tags."""
        sentence = re.sub(r"<whispered\s*>",
                          '<amazon:effect name="whispered">', sentence)
        sentence = re.sub(r"</whispered\s*>", "</amazon:effect>", sentence)
        tags = (r"(?:speak|say-as|voice|prosody|break|emphasis|sub|lang|phoneme|w|p|s|mark|"
                r"amazon:(?:auto-breaths|effect|domain))")
        text_type = "ssml" if re.search(rf"</?{tags}(?:\s[^>]*)?/?>", sentence) else "text"
        if text_type == "ssml" and not re.search(r"<speak(?:\s|>)", sentence):
            sentence = f"<speak>{sentence}</speak>"
        return sentence, text_type

    def _synthesis_request(self, sentence, lang=None, voice=None):
        """Build a Polly request with validated voice selection and prepared text."""
        voice, lang = self._resolve_voice(lang, voice)
        sentence, text_type = self._prepare_text(sentence)
        request = dict(OutputFormat=self.output_format, Text=sentence,
                       Engine=self.engine, TextType=text_type, VoiceId=voice)
        request["SampleRate"] = self.sample_rate
        if self.lexicon_names:
            request["LexiconNames"] = list(self.lexicon_names)
        if lang:
            request["LanguageCode"] = lang
        return request

    @staticmethod
    def _temporary_audio(wav_file):
        directory = os.path.dirname(os.path.abspath(wav_file))
        os.makedirs(directory, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=".polly-", dir=directory)
        os.close(fd)
        return path

    def get_tts(self, sentence, wav_file, lang=None, voice=None):
        """Write synthesized audio to the supplied path and return the OVOS file tuple."""
        response = self.polly.synthesize_speech(
            **self._synthesis_request(sentence, lang, voice))
        path = None
        try:
            with closing(response["AudioStream"]) as stream:
                path = self._temporary_audio(wav_file)
                if self.output_format == "pcm":
                    with wave.open(path, "wb") as audio:
                        audio.setparams((1, 2, int(self.sample_rate), 0, "NONE", "not compressed"))
                        for chunk in stream.iter_chunks(chunk_size=self.chunk_size):
                            audio.writeframesraw(chunk)
                else:
                    with open(path, "wb") as audio:
                        for chunk in stream.iter_chunks(chunk_size=self.chunk_size):
                            audio.write(chunk)
            os.replace(path, wav_file)
        finally:
            if path and os.path.exists(path):
                os.unlink(path)
        return wav_file, None

    async def stream_tts(self, sentence, lang=None, voice=None):
        """Yield encoded audio with backpressure; boto3 never blocks the event loop."""
        request = await asyncio.to_thread(self._synthesis_request, sentence, lang, voice)
        response_lock = threading.Lock()
        cancelled = threading.Event()
        received = {}

        def send_request():
            result = self.polly.synthesize_speech(**request)
            with response_lock:
                if cancelled.is_set():
                    result["AudioStream"].close()
                else:
                    received["response"] = result
            return result

        try:
            response = await asyncio.to_thread(send_request)
        except asyncio.CancelledError:
            # Cleanup belongs to the worker too: the event loop may already be
            # shutting down when an uncancellable network request completes.
            with response_lock:
                cancelled.set()
                if "response" in received:
                    received["response"]["AudioStream"].close()
            raise
        stream = response["AudioStream"]
        try:
            if self.output_format == "pcm":
                # Unknown-length WAV header for pipe playback; repaired on disk.
                rate = int(self.sample_rate)
                yield struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 0xFFFFFFFF,
                                  b"WAVE", b"fmt ", 16, 1, 1, rate, rate * 2,
                                  2, 16, b"data", 0xFFFFFFFF)
            while True:
                chunk = await asyncio.to_thread(stream.read, self.chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            stream.close()

    def init(self, bus=None, playback=None, callbacks=None):
        """Use interruptible default callbacks while accepting custom players."""
        from .playback import PollyStreamingCallbacks
        if callbacks is None:
            callbacks = PollyStreamingCallbacks(bus, tts_config=self.config)
        super().init(bus, playback, callbacks)

    @staticmethod
    def _abort_player(callbacks):
        """Request prompt interruption from players supporting stream_abort."""
        abort = getattr(callbacks, "stream_abort", None)
        if callable(abort):
            abort()

    def stop(self):
        """Stop queued audio and interrupt active streaming playback on its loop."""
        super().stop()
        with self._streams_lock:
            active = [(task, state) for task, state in self._active_streams.items()
                      if not state[1].is_set()]
            for _, (_, stopped, _) in active:
                # Repeated stop calls must not cancel cleanup a second time.
                stopped.set()
        for task, (loop, stopped, callbacks) in active:
            self._abort_player(callbacks)
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(task.cancel)

    async def _playback_call(self, callbacks, method, *args):
        """Keep pipe writes off the event loop and finish cancelled worker calls."""
        pending = asyncio.create_task(asyncio.to_thread(getattr(callbacks, method), *args))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            self._abort_player(callbacks)
            # A late stream_start can create a player after the first abort.
            try:
                with suppress(Exception):
                    await pending
            finally:
                self._abort_player(callbacks)
            raise

    def _register_stream_audio(self, sentence, wav_file, kwargs):
        """Register an existing OVOS cache file without advancing persistence."""
        sentence_hash = hash_sentence(sentence)
        path = Path(wav_file).absolute()
        if path.name != f"{sentence_hash}.{self.audio_ext}":
            return
        ctxt = self._get_ctxt(kwargs)
        cache = ctxt.get_cache(self.audio_ext, self.config)
        allowed = {cache.temporary_cache_dir.absolute(), cache.persistent_cache_dir.absolute()}
        if path.parent in allowed:
            audio = AudioFile(path.parent, sentence_hash, self.audio_ext)
            self._cache_sentence(sentence, ctxt.lang, audio, cache)

    async def generate_audio(self, sentence, wav_file, play_streaming=True,
                             listen=False, message=None, plugin_kwargs=None):
        """Stream playback and atomically publish only complete audio files."""
        kwargs = plugin_kwargs or {}
        path = self._temporary_audio(wav_file)
        started = False
        completed = False
        stopped = threading.Event()
        task = asyncio.current_task()
        callbacks = self.callbacks if play_streaming else None
        if play_streaming:
            with self._streams_lock:
                if self._active_streams:
                    os.unlink(path)
                    raise RuntimeError("Streaming playback is already active")
                self._active_streams[task] = (asyncio.get_running_loop(), stopped, callbacks)
        chunks = self.stream_tts(sentence, **kwargs)
        try:
            if play_streaming:
                started = True
                await self._playback_call(callbacks, "stream_start", message)
            with open(path, "wb") as audio:
                async for chunk in chunks:
                    if stopped.is_set():
                        raise asyncio.CancelledError()
                    audio.write(chunk)
                    if play_streaming:
                        await self._playback_call(callbacks, "stream_chunk", chunk)
                if self.output_format == "pcm":
                    length = audio.tell()
                    audio.seek(4)
                    audio.write(struct.pack("<I", length - 8))
                    audio.seek(40)
                    audio.write(struct.pack("<I", length - 44))
            if stopped.is_set():
                raise asyncio.CancelledError()
            os.replace(path, wav_file)
            if self.enable_cache:
                await asyncio.to_thread(self._register_stream_audio, sentence, wav_file, kwargs)
            completed = True
            return wav_file
        finally:
            try:
                await chunks.aclose()
            finally:
                if os.path.exists(path):
                    os.unlink(path)
                try:
                    if started:
                        if not completed or stopped.is_set():
                            self._abort_player(callbacks)
                        await self._playback_call(
                            callbacks, "stream_stop", listen and completed and not stopped.is_set(), message)
                finally:
                    if play_streaming:
                        with self._streams_lock:
                            self._active_streams.pop(task, None)

    def _execute(self, sentence, ident, listen, **kwargs):
        """Preserve resolved language settings and treat user interruption as normal."""
        if self.config.get("enable_streaming"):
            ctxt = self._get_ctxt(kwargs)
            kwargs.update(ctxt.synth_kwargs)
        try:
            return super()._execute(sentence, ident, listen, **kwargs)
        except asyncio.CancelledError:
            # The synchronous OVOS speech handler must finish its end_audio path.
            return None

    async def stream_text(self, text_chunks, lang=None, voice=None):
        """Bidirectional plain-text input and raw audio output via optional Node SDK."""
        from .bidirectional import stream_text
        chunks = stream_text(self, text_chunks, lang, voice)
        try:
            async for chunk in chunks:
                yield chunk
        finally:
            await chunks.aclose()

    def get_speech_marks(self, sentence, lang=None, voice=None,
                         mark_types=("sentence", "word", "viseme")):
        """Return Polly timing metadata separately from OVOS phoneme data."""
        if self.engine not in {"standard", "neural"}:
            raise ValueError("Speech marks require the standard or neural engine")
        if (not mark_types or isinstance(mark_types, str) or
                not set(mark_types) <= {"sentence", "word", "viseme", "ssml"}):
            raise ValueError("Invalid speech mark types")
        request = self._synthesis_request(sentence, lang, voice)
        request.update(OutputFormat="json", SpeechMarkTypes=list(mark_types))
        request.pop("SampleRate", None)
        response = self.polly.synthesize_speech(**request)
        with closing(response["AudioStream"]) as stream:
            return [json.loads(line) for line in stream.iter_lines() if line]

    @classproperty
    def available_languages(cls) -> set:
        """Return languages supported by this TTS implementation in this state
        This property should be overridden by the derived class to advertise
        what languages that engine supports.
        Returns:
            set: supported languages
        """
        # SDK metadata is available offline and tracks new Polly languages.
        from botocore.session import get_session
        model = get_session().get_service_model("polly")
        return set(model.shape_for("LanguageCode").enum)


class PollyTTSValidator(TTSValidator):
    """Validate local dependencies and language support without synthesizing audio."""
    def __init__(self, tts):
        """Bind validation to the configured Polly TTS instance."""
        super(PollyTTSValidator, self).__init__(tts)

    def validate_lang(self):
        """Reject languages absent from the installed SDK service model."""
        lang = self.tts._language_code(self.tts.lang)
        if lang not in self.tts.available_languages:
            raise ValueError(f"Unsupported Polly language: {lang}")

    def validate_dependencies(self):
        """Report an actionable error when the boto3 dependency is unavailable."""
        try:
            from importlib.util import find_spec
            if find_spec("boto3") is None:
                raise ImportError("boto3")
        except ImportError as exc:
            raise ImportError(
                "PollyTTS dependencies not installed, please run pip install boto3"
            ) from exc

    def get_tts_class(self):
        """Return the plugin class expected by the OVOS validator interface."""
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

"""OVOS streaming callbacks with an explicit interruption path."""
from contextlib import suppress
from threading import Event

from ovos_plugin_manager.templates.tts import StreamingTTSCallbacks


class PollyStreamingCallbacks(StreamingTTSCallbacks):
    """Terminate buffered playback on stop while retaining OVOS audio events."""

    def __init__(self, *args, **kwargs):
        """Track aborts independently of the playback worker thread."""
        super().__init__(*args, **kwargs)
        self._aborted = Event()

    def stream_start(self, message=None):
        """Begin an utterance with a fresh interruption state."""
        self._aborted.clear()
        super().stream_start(message)

    def stream_abort(self):
        """Interrupt the player and unblock pipe writers without draining audio."""
        self._aborted.set()
        process = self._process
        if process is not None:
            with suppress(ProcessLookupError):
                process.kill()

    def stream_stop(self, listen=False, message=None):
        """Reap the player and emit completion events, suppressing listen on abort."""
        process = self._process
        if process is not None:
            try:
                with suppress(OSError):
                    process.stdin.close()
                process.wait()
            finally:
                self._process = None
        super().stream_stop(listen and not self._aborted.is_set(), message)

"""Optional HTTP/2 bridge; boto3 does not implement bidirectional Polly streams."""
import asyncio
import contextlib
import json
import os
from pathlib import Path


async def stream_text(tts, text_chunks, lang=None, voice=None):
    """Yield raw Polly bytes while consuming an async iterator of plain text."""
    if tts.engine != 'generative':
        raise ValueError('Bidirectional streaming requires engine="generative"')
    command = tts.config.get('bidirectional_command') or [
        'node', str(Path(__file__).with_name('bridge') / 'stream.mjs')]
    if not isinstance(command, list) or not command or any(not isinstance(s, str) for s in command):
        raise ValueError('bidirectional_command must be a list of command arguments')
    request = await asyncio.to_thread(tts._synthesis_request, '', lang, voice)
    request.pop('Text')
    request.pop('TextType')
    environment = os.environ.copy()
    if tts.key_id:
        environment.update(AWS_ACCESS_KEY_ID=tts.key_id, AWS_SECRET_ACCESS_KEY=tts.key)
        environment.pop('AWS_SESSION_TOKEN', None)
        if tts.config.get('session_token'):
            environment['AWS_SESSION_TOKEN'] = tts.config['session_token']
    if tts.config.get('profile_name'):
        environment['AWS_PROFILE'] = tts.config['profile_name']
    timeout = float(tts.config.get('bidirectional_timeout', 30))
    if timeout <= 0:
        raise ValueError('bidirectional_timeout must be positive')
    proc = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=environment)

    async def send():
        async def write(value):
            data = (json.dumps(value, ensure_ascii=False) + '\n').encode()
            if len(data) > 65536:
                raise ValueError('Bidirectional input event exceeds 64 KiB')
            proc.stdin.write(data)
            await proc.stdin.drain()
        try:
            await write({'region': tts.region, 'request': request,
                         'timeout_ms': int(timeout * 1000)})
            async for text in text_chunks:
                if not isinstance(text, str) or not text:
                    raise ValueError('Text chunks must be nonempty strings')
                await write({'text': text})
            proc.stdin.close()
            await proc.stdin.wait_closed()
        except BaseException:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
            raise

    sender = asyncio.create_task(send())
    try:
        while True:
            chunk = await asyncio.wait_for(proc.stdout.read(tts.chunk_size), timeout)
            if not chunk:
                break
            yield chunk
        # Observe producer errors and do not wait forever if the child exits early.
        if not sender.done():
            await asyncio.wait_for(asyncio.shield(sender), timeout)
        else:
            await sender
        code = await asyncio.wait_for(proc.wait(), timeout)
        if code:
            raise RuntimeError(f'Polly bidirectional helper failed (exit {code}); '
                               'check installation, credentials, region, and voice')
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()

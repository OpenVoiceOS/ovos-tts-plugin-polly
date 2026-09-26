"""Opt-in live benchmark. Default simulation validates the measurement pipeline."""
import argparse
import asyncio
import io
import json
import math
import platform
import tempfile
import time
import tracemalloc
from pathlib import Path
from unittest.mock import patch

import boto3
from botocore.response import StreamingBody
from ovos_tts_plugin_polly import PollyTTS
from ovos_plugin_manager.templates.tts import TTSContext


class SimulatedPolly:
    """Synthetic transport, not a model or a predictor of AWS performance."""
    def describe_voices(self, **kwargs):
        lang = kwargs.get('LanguageCode', 'en-US')
        return {'Voices': [{'Id': 'Gabrielle' if lang == 'fr-CA' else 'Matthew',
                            'LanguageCode': lang}]}

    def synthesize_speech(self, **kwargs):
        time.sleep(0.005)
        return {'AudioStream': StreamingBody(io.BytesIO(b'0' * 16384), 16384)}


def summarize(rows):
    """Nearest-rank percentiles; failures stay visible in their own count."""
    result = {}
    for mode in sorted({r['mode'] for r in rows}):
        group = [r for r in rows if r['mode'] == mode]
        stats = {'requests': len(group), 'errors': sum('error' in r for r in group)}
        for field in ('first_audio_byte_ms', 'complete_ms'):
            values = sorted(r[field] for r in group if r.get(field) is not None and 'error' not in r)
            if values:
                stats[field] = {f'p{p}': values[math.ceil(len(values) * p / 100) - 1]
                                for p in (50, 95)}
        result[mode] = stats
    return result


async def measure(tts, item, mode, destination):
    started = time.perf_counter()
    row = {'id': item['id'], 'lang': item['lang'], 'mode': mode}
    try:
        if mode == 'stream':
            first = None
            skip = 44 if tts.output_format == 'pcm' else 0
            size = 0
            chunks = tts.stream_tts(item['text'], lang=item['lang'])
            try:
                async for chunk in chunks:
                    audio_length = max(0, len(chunk) - skip)
                    skip = max(0, skip - len(chunk))
                    size += audio_length
                    if first is None and audio_length:
                        first = (time.perf_counter() - started) * 1000
            finally:
                await chunks.aclose()
            row.update(first_audio_byte_ms=first, bytes=size)
        elif mode == 'uncached_file':
            await asyncio.to_thread(tts.get_tts, item['text'], str(destination), item['lang'])
            row['bytes'] = destination.stat().st_size
        else:
            audio, _ = await asyncio.to_thread(tts.synth, item['text'], lang=item['lang'])
            row['bytes'] = Path(str(audio)).stat().st_size
        row['complete_ms'] = (time.perf_counter() - started) * 1000
    except Exception as exc:
        # Exception text can contain request data. Record only its class.
        row['error'] = type(exc).__name__
    return row


async def run(tts, corpus, args, directory):
    rows = []
    semaphore = asyncio.Semaphore(args.concurrency)
    async def limited(item, mode, index):
        async with semaphore:
            return await measure(tts, item, mode, directory / f'{index}.{tts.audio_ext}')
    # First request includes lazy catalog discovery. Subsequent requests use warm metadata.
    cold = await measure(tts, corpus[0], 'uncached_file', directory / f'cold.{tts.audio_ext}')
    cold['mode'] = 'cold_file'
    rows.append(cold)
    for mode in ('uncached_file', 'stream'):
        items = corpus * args.repeat
        rows.extend(await asyncio.gather(*(limited(item, mode, i) for i, item in enumerate(items))))
    # Exercise OVOS cache serially; only uncached modes measure concurrent synthesis.
    for item in corpus:
        rows.append(await measure(tts, item, 'cache_miss', directory / 'unused'))
    for _ in range(args.repeat):
        for item in corpus:
            rows.append(await measure(tts, item, 'cache_hit', directory / 'unused'))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Make billable AWS requests')
    parser.add_argument('--config', type=Path, help='JSON containing only the plugin config block')
    parser.add_argument('--corpus', type=Path, default=Path(__file__).with_name('corpus.json'))
    parser.add_argument('--output', type=Path, default=Path('benchmark.json'))
    parser.add_argument('--samples', type=Path, help='Keep uncached audio for listening (live mode only)')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--concurrency', type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1 or args.concurrency < 1:
        parser.error('repeat and concurrency must be positive')
    if args.samples and not args.live:
        parser.error('simulated audio cannot be used for listening')
    config = json.loads(args.config.read_text()) if args.config else {'engine': 'neural'}
    corpus = json.loads(args.corpus.read_text())
    if not corpus:
        parser.error('corpus must not be empty')
    with tempfile.TemporaryDirectory(prefix='polly-benchmark-') as temporary:
        directory = Path(temporary)
        config.update(enable_cache=True, persist_cache=False, preloaded_cache=str(directory / 'cache'))
        # Keep all framework audio in the benchmark's isolated temporary directory.
        with patch('ovos_plugin_manager.utils.tts_cache.get_tmp_cache_dir', return_value=str(directory / 'cache')):
            if args.live:
                tts = PollyTTS(config=config)
            else:
                with patch('boto3.Session') as session:
                    session.return_value.client.return_value = SimulatedPolly()
                    tts = PollyTTS(config=config)
            TTSContext._caches.clear()
            sample_dir = args.samples or directory / 'samples'
            sample_dir.mkdir(parents=True, exist_ok=True)
            tracemalloc.start()
            started = time.perf_counter()
            rows = asyncio.run(run(tts, corpus, args, sample_dir))
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            report = {
                'simulated': not args.live, 'python': platform.python_version(),
                'boto3': boto3.__version__, 'region': tts.region, 'engine': tts.engine,
                'output_format': tts.output_format, 'sample_rate': tts.sample_rate,
                'concurrency': args.concurrency, 'repeat': args.repeat,
                'elapsed_s': elapsed, 'peak_python_bytes': peak,
                'summary': summarize(rows), 'requests': rows,
                'limitations': 'First audio byte is not first audible sound. Memory excludes native allocations. '
                              'Simulation is not an AWS latency measurement. No automatic pronunciation scoring.',
            }
            args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Wrote {args.output}; simulated={not args.live}; errors={sum("error" in r for r in rows)}')
    return int(any('error' in r for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())

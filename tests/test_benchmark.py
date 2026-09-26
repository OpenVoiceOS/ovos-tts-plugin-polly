import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).parents[1] / 'benchmarks/run.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_percentiles_and_failures():
    rows = [{'mode': 'stream', 'complete_ms': n, 'first_audio_byte_ms': n / 2}
            for n in range(1, 101)]
    rows.append({'mode': 'stream', 'error': 'TimeoutError'})
    result = benchmark.summarize(rows)['stream']
    assert result['requests'] == 101
    assert result['errors'] == 1
    assert result['complete_ms'] == {'p50': 50, 'p95': 95}
    assert result['first_audio_byte_ms'] == {'p50': 25, 'p95': 47.5}

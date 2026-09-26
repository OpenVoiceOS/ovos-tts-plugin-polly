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


def test_simulated_cli_runs_all_measurement_modes(tmp_path):
    import json
    import subprocess
    import sys
    output = tmp_path / 'report.json'
    subprocess.run([sys.executable, str(Path(benchmark.__file__)), '--repeat', '1',
                    '--concurrency', '2', '--output', str(output)],
                   check=True, capture_output=True, text=True, timeout=30)
    report = json.loads(output.read_text())
    assert report['simulated'] is True
    assert set(report['summary']) == {'cold_file', 'uncached_file', 'stream', 'cache_miss', 'cache_hit'}
    assert all(result['errors'] == 0 for result in report['summary'].values())
    assert report['summary']['stream']['first_audio_byte_ms']['p50'] >= 0

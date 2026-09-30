"""Test scoring, not model intelligence; live evidence is collected separately."""
import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts/benchmark_jev.py'
spec = importlib.util.spec_from_file_location('jev_benchmark', path)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def row(cid, mode, ok, latency=100):
    return dict(case=cid, group='safety', mode=mode, correct=ok, latency_ms=latency,
                actual={'act': 'plan' if ok else 'explain', 'intent': 'energy_planning', 'source': 'model'},
                deepseek_calls=[])


def test_cases_unique_frozen_and_balanced():
    data = bench.cases()
    assert len(data) == 48
    assert len({c['id'] for c in data}) == 48
    assert all(sum(c['group'] == g for c in data) == 6
               for g in ('energy', 'travel', 'context', 'safety', 'general'))


def test_repetitions_do_not_inflate_significance():
    data = [dict(id='one', split='new', group='safety')]
    rows = [row('one', m, m == 'active') for _ in range(10) for m in ('off', 'active')]
    score = bench.summarize(rows, data, 10)['new']
    assert score['unique_case_wins'] == 1
    assert score['exact_mcnemar_p'] == 1
    assert not score['improvement_gate']


def test_latency_guard_and_critical_regression_fail_gate():
    data = [dict(id=str(i), split='new', group='safety', critical=True) for i in range(10)]
    rows = [row(c['id'], m, m == 'active') for c in data for _ in range(2) for m in ('off', 'active')]
    assert bench.summarize(rows, data, 2)['new']['improvement_gate']
    for r in rows:
        if r['mode'] == 'active':
            r['latency_ms'] = 200
    assert not bench.summarize(rows, data, 2)['new']['improvement_gate']
    for r in rows:
        r['latency_ms'] = 100
        if r['case'] == '0':
            r['correct'] = r['mode'] == 'off'
    score = bench.summarize(rows, data, 2)['new']
    assert score['critical_regressions'] == ['0']
    assert not score['improvement_gate']


def test_missing_results_cannot_pass():
    data = [dict(id='one', split='new', group='safety')]
    score = bench.summarize([row('one', 'active', True)], data, 2)['new']
    assert not score['complete']
    assert score['accuracy_delta'] is None
    assert not score['improvement_gate']

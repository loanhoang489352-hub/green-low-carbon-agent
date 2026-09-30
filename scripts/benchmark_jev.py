"""Frozen paired routing benchmark. --live spends provider credits; no user DB writes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from eval_jev_impact import CASES, JevEvents


def cases():
    new = json.loads((ROOT / 'tests/eval/jev_holdout.json').read_text(encoding='utf-8'))
    for case in new:
        case['split'] = 'new'
    old = [dict(id='reg_' + cid, text=text, state=state, act=act, intent=intent,
                split='regression', group='known') for cid, text, state, act, intent in CASES]
    result = new + old
    if len({c['id'] for c in result}) != len(result):
        raise ValueError('duplicate IDs')
    return result


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def summarize(rows, dataset, repeats):
    """Repeated calls are NOT independent samples: infer on distinct case IDs only."""
    result = {}
    for split in ('new', 'regression'):
        subset = [c for c in dataset if c['split'] == split]
        selected = [r for r in rows if r['case'] in {c['id'] for c in subset}]
        stats = {}
        for mode in ('off', 'active'):
            arm = [r for r in selected if r['mode'] == mode]
            latencies = [r['latency_ms'] for r in arm]
            stats[mode] = dict(calls=len(arm), correct=sum(r['correct'] for r in arm),
                accuracy=sum(r['correct'] for r in arm) / len(arm) if arm else None,
                median_ms=statistics.median(latencies) if arm else None,
                p95_ms=percentile(latencies, .95),
                source_counts=dict(Counter(r['actual'].get('source', 'exception') for r in arm)),
                deepseek_calls=sum(len(r['deepseek_calls']) for r in arm),
                exceptions=sum(bool(r.get('exception')) for r in arm),
                unstable_cases=sum(len({(r['actual'].get('act'), r['actual'].get('intent'))
                    for r in arm if r['case'] == c['id']}) > 1 for c in subset))
        complete = bool(subset) and all(sum(r['case'] == c['id'] and r['mode'] == m for r in selected) == repeats
                       for c in subset for m in ('off', 'active'))
        wins, losses, critical_regressions, changed = 0, 0, [], []
        for c in subset:
            arm_rows = {m: [r for r in selected if r['case'] == c['id'] and r['mode'] == m]
                        for m in ('off', 'active')}
            stable_pass = {m: len(a) == repeats and all(r['correct'] for r in a)
                           for m, a in arm_rows.items()}
            win = stable_pass['active'] and not stable_pass['off']
            loss = stable_pass['off'] and not stable_pass['active']
            wins += win
            losses += loss
            if loss and c.get('critical'):
                critical_regressions.append(c['id'])
            if win or loss:
                changed.append({'id': c['id'], 'change': 'win' if win else 'loss'})
        n = wins + losses
        p = min(1., 2 * sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2**n) if n else 1.
        delta = (stats['active']['accuracy'] - stats['off']['accuracy']) if complete else None
        # Predeclared practical + statistical + guardrail gate; no post-hoc tuning.
        gate = bool(complete and delta >= .10 and p <= .05 and not critical_regressions
                    and stats['active']['p95_ms'] <= 1.2 * max(1, stats['off']['p95_ms']))
        result[split] = dict(arms=stats, complete=complete, accuracy_delta=delta,
            unique_case_wins=wins, unique_case_losses=losses, exact_mcnemar_p=p,
            critical_regressions=critical_regressions, changes=changed, improvement_gate=gate)
    result['per_group'] = {g: {m: {'correct': sum(r['correct'] for r in rows
          if r['group'] == g and r['mode'] == m), 'total': sum(r['group'] == g and r['mode'] == m for r in rows)}
          for m in ('off', 'active')} for g in sorted({c['group'] for c in dataset})}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--repeats', type=int, choices=(2, 3), default=2)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    dataset = cases()
    protocol = {'accuracy_gain_min': .10, 'exact_mcnemar_p_max': .05,
        'critical_regressions_max': 0, 'p95_ratio_max': 1.2,
        'inference_unit': 'distinct case; success requires every repetition correct',
        'scope': 'routing only; no final recommendation quality/cost/E2E claim',
        'labels': 'author-reviewed synthetic cases, not independent human gold labels',
        'repeats': args.repeats, 'seed': 20260929, 'max_seconds': 600}
    output = dict(start_utc=datetime.now(timezone.utc).isoformat(), protocol=protocol,
        dataset=dataset, dataset_sha256=hashlib.sha256(json.dumps(dataset, ensure_ascii=False,
        sort_keys=True).encode()).hexdigest(), rows=[], completed=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit('Refusing to overwrite previous evidence; use a new output path.')

    def save():
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')

    save()  # Freeze labels and gates before ANY calls.
    if not args.live:
        print(json.dumps({'frozen_cases': len(dataset), 'live_calls': 0}))
        return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not all(os.getenv(k, '').strip() for k in ('DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY')):
        raise SystemExit('Both provider keys required; no request sent.')
    from agent.intent import IntentRecognizer
    from agent.routing.router import Router, _fast_classifier
    from llm.client import set_llm_user
    os.environ['UNDERSTANDING_MODE'] = 'hybrid'
    os.environ['LLM_MOCK'] = 'false'
    set_llm_user(None)
    output['config'] = {k: os.getenv(k) for k in ('API_PROVIDER', 'API_MODEL', 'JEV_PROVIDER',
        'JEV_MODEL', 'JEV_TIMEOUT_SECONDS', 'JEV_MIN_CONFIDENCE')}
    output['code_sha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
        for p in ('src/agent/routing/router.py', 'src/agent/routing/jev.py',
                  'src/agent/routing/state_machine.py', 'src/agent/intent.py')}
    logging.getLogger().setLevel(logging.CRITICAL)
    events = JevEvents()
    logger = logging.getLogger('agent.routing.jev')
    logger.setLevel(logging.INFO)
    logger.addHandler(events)
    logger.propagate = False
    client = _fast_classifier()
    original_chat = client.chat
    calls = []

    def tracked(*a, **kw):
        item = {'error': True}
        calls.append(item)
        response = original_chat(*a, **kw)
        item.update(model=response.model, error=bool(response.error), usage=response.usage)
        return response

    client.chat = tracked
    started = time.monotonic()
    try:
        for repeat in range(args.repeats):
            shuffled = list(dataset)
            random.Random(20260929 + repeat).shuffle(shuffled)
            for index, case in enumerate(shuffled):
                if time.monotonic() - started > protocol['max_seconds']:
                    output['stopped'] = 'wall_time_budget'
                    break
                modes = ('off', 'active') if (index + repeat) % 2 == 0 else ('active', 'off')
                for mode in modes:
                    os.environ['JEV_ROUTING_MODE'] = mode
                    begin = time.monotonic()
                    nc, ne = len(calls), len(events.events)
                    row = dict(case=case['id'], group=case['group'], repeat=repeat, mode=mode)
                    try:
                        demand = Router(IntentRecognizer()).understand(case['text'], case['state'])
                        row['actual'] = dict(act=demand.act, intent=demand.intent, source=demand.source)
                        row['correct'] = (demand.act, demand.intent) == (case['act'], case['intent'])
                    except Exception as exc:
                        row.update(actual={}, correct=False, exception=type(exc).__name__)
                    row.update(latency_ms=round((time.monotonic() - begin) * 1000),
                               deepseek_calls=calls[nc:], jev_events=events.events[ne:])
                    output['rows'].append(row)
                    save()
                print(json.dumps({'round': repeat + 1, 'pair': index + 1, 'of': len(dataset)}), flush=True)
            if output.get('stopped'):
                break
    finally:
        client.chat = original_chat
        output['summary'] = summarize(output['rows'], dataset, args.repeats)
        output['completed'] = len(output['rows']) == len(dataset) * args.repeats * 2
        output['elapsed_seconds'] = round(time.monotonic() - started, 1)
        save()
    print(json.dumps(output['summary'], ensure_ascii=False), flush=True)
    return 0 if output['completed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

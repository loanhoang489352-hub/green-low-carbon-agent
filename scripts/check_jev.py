"""Read-only Jev acceptance: synthetic messages, no accounts/profile writes.

Run from any directory: python scripts/check_jev.py [--live].
Only --live calls the configured provider (three bounded, potentially billed calls).
"""
import argparse
import importlib.util
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from agent.intent import IntentRecognizer
    from agent.routing import Router
    from agent.skills import SkillContext
    spec = importlib.util.spec_from_file_location('jev_skill_check', ROOT / 'plugins/jev_skill.py')
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    logging.basicConfig(level=logging.INFO)
    # Exclude HTTP logging; no raw provider response or credentials in output.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    status = plugin.configuration_status()
    print(json.dumps({'configuration': status}, ensure_ascii=True))
    if not args.live:
        return 0 if status['skill_installed'] else 1
    cases = [
        ('energy', '给我家个性化定制节能方案，尽量省事，不想换家电', {}),
        ('travel', '明早从重庆北站到解放碑，公交地铁优先，不骑车', {}),
        ('energy', '还是按我家现在的情况重新安排一下用能吧', {
            'active_domain': 'energy', 'recent': [
                {'role': 'assistant', 'content': '刚才讨论了你家空调与热水器的节能安排。'}]}),
    ]
    passed = 0
    for index, (expected, message, state) in enumerate(cases):
        start = time.monotonic()
        if index == 2:
            result = plugin.JevRoutingSkill().execute(SkillContext(
                message=message, metadata={'dialogue_state': state}))
            actual = result.data if result.success else {}
        else:
            demand = Router(IntentRecognizer()).understand(message, state)
            actual = {'domain': demand.domain, 'act': demand.act, 'source': demand.source}
        ok = actual.get('domain') == expected and actual.get('act') == 'plan' and actual.get('source') == 'jev'
        passed += int(ok)
        print(json.dumps({'case': index + 1, 'passed': ok, 'domain': actual.get('domain'),
                          'source': actual.get('source'), 'latency_ms': round((time.monotonic() - start) * 1000)}))
    print(json.dumps({'live_passed': passed, 'total': len(cases)}))
    return 0 if passed == len(cases) else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Paired live routing evaluation; synthetic inputs only, no user DB writes.

Explicit --live required. Runs up to 18 pairs plus two brain calls; billed APIs.
Does not change .env or the running server; writes a sanitized JSON evidence file.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import statistics
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

# Fixed labels set before running; compare act+intent, not arbitrary explanation domain.
CASES = [
    ('explicit_energy', '给我家个性化定制节能方案', {}, 'plan', 'energy_planning'),
    ('indirect_energy', '我家用能开销想降下来，又不想折腾换家电', {}, 'plan', 'energy_planning'),
    ('water_gas', '家里水费和燃气费一直偏高，给些适合我们家的安排', {}, 'plan', 'energy_planning'),
    ('constraints_energy', '我们家五个人有老人，舒服和省事最重要，做个节电计划', {}, 'plan', 'energy_planning'),
    ('explicit_travel', '明早从重庆北站到解放碑，公交地铁优先，不骑车', {}, 'plan', 'travel_planning'),
    ('indirect_travel', '明天要去公司，想少排点碳，帮我选个合适的交通方式', {}, 'plan', 'travel_planning'),
    ('travel_constraint', '周末带老人从西单到颐和园，少走路，比较公交和自驾', {}, 'plan', 'travel_planning'),
    ('past_action', '今天已经坐地铁回家了', {}, 'report', 'action_report'),
    ('negative_plan', '我不需要节能方案，只想知道电费怎么算', {}, 'explain', 'knowledge_query'),
    ('hypothetical', '假如我家有燃气灶，如何节能', {}, 'explain', 'knowledge_query'),
    ('cancel', '取消', {'active_domain': 'energy'}, 'cancel', 'feedback'),
    ('ambiguous', '这个弄一下', {}, 'clarify', 'unknown'),
    ('energy_followup', '还是按我家现在的情况重新安排一下吧', {'active_domain': 'energy', 'recent': [
        {'role': 'assistant', 'content': '刚才讨论的是你家的空调和热水器节能计划。'}]}, 'plan', 'energy_planning'),
    ('travel_followup', '改成明早八点到，少走一点', {'active_domain': 'travel', 'recent': [
        {'role': 'user', 'content': '从北京西站到国贸给我规划路线'}]}, 'plan', 'travel_planning'),
    ('slot', '四个', {'active_domain': 'energy', 'expected_slot': 'family_size'}, 'update', 'energy_planning'),
    ('general_advice', '给我一些低碳生活建议', {}, 'advise', 'advice_request'),
    ('energy_explanation', '空调为什么这么耗电', {}, 'explain', 'knowledge_query'),
    ('multi_task', '先规划明天的地铁路线，再帮我看看家里怎么节电', {}, 'clarify', 'unknown'),
]


class JevEvents(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events = []

    def emit(self, record):
        if record.msg.startswith('jev_route '):
            self.events.append(record.getMessage())  # Client logs only whitelisted metadata.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv, dotenv_values
    load_dotenv(ROOT / '.env')
    file_values = dotenv_values(ROOT / '.env')
    from agent.intent import IntentRecognizer
    from agent.routing import router
    from llm import get_llm_client
    from llm.client import set_llm_user
    logging.getLogger().setLevel(logging.CRITICAL)
    events = JevEvents()
    jev_log = logging.getLogger('agent.routing.jev')
    jev_log.setLevel(logging.INFO)
    jev_log.addHandler(events)
    jev_log.propagate = False
    watched = ('API_PROVIDER', 'API_MODEL', 'DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY')
    original = {k: os.getenv(k) for k in watched}
    original_mode = os.getenv('JEV_ROUTING_MODE')
    set_llm_user(None)
    brain = get_llm_client()
    fast = router._fast_classifier()
    classifier_calls = []
    original_chat = fast.chat

    def tracked_chat(*a, **kw):
        response = original_chat(*a, **kw)
        classifier_calls.append({'model': response.model, 'error': bool(response.error),
                                 'usage': response.usage})
        return response

    fast.chat = tracked_chat
    output = {'time_utc': datetime.now(timezone.utc).isoformat(), 'cases_frozen_before_run': True,
              'key_presence_in_env_file': {k: bool(file_values.get(k, '').strip())
                  for k in ('OPENROUTER_API_KEY', 'DEEPSEEK_API_KEY')},
              'config': {k: os.getenv(k) for k in ('API_PROVIDER', 'API_MODEL', 'JEV_PROVIDER', 'JEV_MODEL', 'JEV_TIMEOUT_SECONDS')},
              'brain': [], 'rows': []}

    def check_brain(mode):
        os.environ['JEV_ROUTING_MODE'] = mode
        start = time.monotonic()
        response = brain.chat([
            {'role': 'system', 'content': '用中文简短回答，不声称已控制设备，不编造节省数字。'},
            {'role': 'user', 'content': '虚构家庭：三个人，有空调和电热水器，不想购买新设备。请给两条省事的家庭节能建议。'}
        ], max_tokens=1800, timeout=35, max_retries=0)
        ok = not response.error and bool(response.content.strip()) and response.model != 'mock'
        output['brain'].append({'jev_mode': mode, 'ok': ok, 'class': type(brain).__name__,
            'configured_model': brain.model, 'response_model': response.model,
            'latency_ms': round((time.monotonic() - start) * 1000), 'usage': response.usage,
            'error_present': bool(response.error), 'finish_reason': response.finish_reason,
            'answer': response.content if ok else ''})
        print(json.dumps({'brain_mode': mode, 'ok': ok, 'model': response.model}), flush=True)

    def save():
        target = ROOT / 'data' / 'jev-impact-20260929.json'
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        check_brain('off')
        save()
        for index, (cid, text, state, act, intent) in enumerate(CASES):
            # Alternate order to reduce order/network effects; both arms use real APIs.
            for mode in (('off', 'active') if index % 2 == 0 else ('active', 'off')):
                os.environ['JEV_ROUTING_MODE'] = mode
                start = time.monotonic()
                count, event_start = len(classifier_calls), len(events.events)
                result = router.Router(IntentRecognizer()).understand(text, state)
                output['rows'].append({'case': cid, 'input': text, 'state': state, 'mode': mode,
                    'expected': {'act': act, 'intent': intent}, 'actual': {'act': result.act, 'intent': result.intent, 'source': result.source},
                    'correct': (result.act, result.intent) == (act, intent),
                    'latency_ms': round((time.monotonic() - start) * 1000),
                    'deepseek_classifier_calls': classifier_calls[count:], 'jev_events': events.events[event_start:]})
                save()
            print(json.dumps({'completed_pairs': index + 1, 'total': len(CASES)}), flush=True)
        check_brain('active')
        output['brain_client_unchanged'] = get_llm_client() is brain
        output['provider_model_and_keys_unchanged'] = all(os.getenv(k) == v for k, v in original.items())
        output['summary'] = {}
        for mode in ('off', 'active'):
            rows = [r for r in output['rows'] if r['mode'] == mode]
            timed = [r['latency_ms'] for r in rows if r['deepseek_classifier_calls'] or r['jev_events']]
            output['summary'][mode] = {'correct': sum(r['correct'] for r in rows), 'total': len(rows),
                'median_all_ms': statistics.median(r['latency_ms'] for r in rows),
                'median_model_path_ms': statistics.median(timed) if timed else None,
                'deepseek_classifier_calls': sum(len(r['deepseek_classifier_calls']) for r in rows),
                'jev_accepted': sum(r['actual']['source'] == 'jev' for r in rows),
                'jev_attempted': sum(bool(r['jev_events']) for r in rows)}
        save()
        print(json.dumps({'summary': output['summary'], 'brain_ok': [r['ok'] for r in output['brain']],
                          'config_unchanged': output['provider_model_and_keys_unchanged']}, ensure_ascii=True), flush=True)
    finally:
        fast.chat = original_chat
        if original_mode is None:
            os.environ.pop('JEV_ROUTING_MODE', None)
        else:
            os.environ['JEV_ROUTING_MODE'] = original_mode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

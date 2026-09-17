"""确定性路由规则链:取消/续接/继续/多任务/天气/知识/假设/填槽。

这里按**原始顺序**跑所有「不需要 LLM」的确定性规则(有状态过渡 + 无状态关键词前置)。
顺序不能随意重排:无状态关键词前置(天气/知识/假设)必须夹在「继续」和「填槽」之间,
否则「北京天气如何」带 hints 时会被填槽的 hints 兜底误判成 update。

每个 transition_* 返回 Optional[Demand],None 表示不适用,继续下一条。
"""
import re
from typing import Optional

from .demand import Demand
from .patterns import ENERGY, TRAVEL, EXPLAIN, NEGATIVE_PLAN, domain_of, planning_intent


class DialogStateMachine:
    """确定性路由规则链(继续/取消/填槽 + 关键词前置)。

    handle() 按固定顺序尝试各规则;命中即返回 Demand,否则返回 None(交给路由器继续)。
    recurse: 回调,用于续接 pending 任务时重新解释原任务消息(通常是路由器的 understand)。
    """

    def handle(self, text, state=None, hints=None, profile=None, recurse=None) -> Optional[Demand]:
        state = state or {}
        for fn in (self._cancel, self._resume_pending, self._continue_active,
                   self._split_multi_request, self._weather_explain, self._explain_negative,
                   self._hypothetical, self._continue_resume, self._fill_slot):
            demand = fn(text, state, hints, profile, recurse)
            if demand is not None:
                return demand
        return None

    # ---- 各规则(原始顺序) ----

    def _cancel(self, text, state, hints, profile, recurse):
        if re.fullmatch(r'\s*(取消|算了|不做了|停止|取消当前任务)[吧。！!\s]*', text):
            return Demand(domain=state.get('active_domain', '') or domain_of(text),
                          act='cancel', intent='feedback', relation='cancel',
                          evidence=text[:300], message=text)
        return None

    def _resume_pending(self, text, state, hints, profile, recurse):
        pending = state.get('pending_tasks') or []
        if pending and re.fullmatch(r'(?:先|继续|处理|看看|做)?(?:家庭节能|节能|出行|低碳出行|继续|下一个)[吧。\s]*', text):
            wanted = 'energy' if '节能' in text else 'travel' if '出行' in text else pending[0]['domain']
            task = next((p for p in pending if p['domain'] == wanted), None)
            if task:
                if not (re.search(ENERGY, task['message']) and re.search(TRAVEL, task['message'])):
                    if recurse is None:
                        return None
                    selected = recurse(task['message'], {}, profile, hints={})
                    selected.relation = 'resume'
                    selected.domain = wanted
                    return selected
                return Demand(domain=wanted, act='plan', intent=planning_intent(wanted),
                              relation='resume', message=task['message'], evidence=text[:300])
        return None

    def _continue_active(self, text, state, hints, profile, recurse):
        # 否定句式("不想继续节能")不该被当作 resume,交给后面的 _explain_negative 处理
        if re.search(r'(?:不想|不需要|不用|不要|别|算了)\s*继续', text):
            return None
        if re.search(r'继续.*(?:节能|出行)', text):
            wanted = 'energy' if '节能' in text else 'travel'
            previous = (state.get('last_requests') or {}).get(wanted)
            if previous or state.get('active_domain', '') == wanted:
                return Demand(domain=wanted, act='plan', intent=planning_intent(wanted),
                              relation='resume',
                              message='请按当前画像继续家庭节能规划' if wanted == 'energy' else previous or text,
                              evidence=text[:300])
        return None

    def _split_multi_request(self, text, state, hints, profile, recurse):
        if re.search(ENERGY, text) and re.search(TRAVEL, text) and re.search(r'再|同时|然后|另外|以及|先', text):
            parts = re.split(r'[，,；;]|然后|再帮我|再看看|另外', text)
            tasks = []
            for part in parts:
                dom = domain_of(part)
                if dom in ('energy', 'travel') and not any(t['domain'] == dom for t in tasks):
                    tasks.append({'domain': dom, 'message': part.strip()})
            if len(tasks) != 2:
                tasks = [{'domain': dom, 'message': text} for dom in ('travel', 'energy')]
            return Demand(domain=domain_of(text), act='clarify', intent='unknown', relation='new',
                          tasks=tasks,
                          question='你提到了出行和家庭节能。先处理哪一个？另一项我会保留。',
                          evidence=text[:300], message=text)
        return None

    def _weather_explain(self, text, state, hints, profile, recurse):
        if re.search(r'天气|气温|下雨|下雪', text) and not re.search(TRAVEL, text):
            return Demand(domain='general', act='explain', intent='knowledge_query',
                          relation='interrupt' if state.get('active_domain', '') else 'new',
                          evidence=text[:300], message=text)
        return None

    def _explain_negative(self, text, state, hints, profile, recurse):
        if re.search(EXPLAIN, text) or re.search(r'二十四节气|什么.*节气|节气.*是什么', text) or re.search(NEGATIVE_PLAN, text):
            return Demand(domain=domain_of(text), act='explain', intent='knowledge_query',
                          relation='interrupt' if state.get('active_domain', '') else 'new',
                          evidence=text[:300], message=text)
        return None

    def _hypothetical(self, text, state, hints, profile, recurse):
        if re.search(r'假如|假设|如果我家|如果有', text):
            return Demand(domain=domain_of(text), act='explain', intent='knowledge_query',
                          relation='interrupt' if state.get('active_domain', '') else 'new',
                          evidence=text[:300], message=text)
        return None

    def _continue_resume(self, text, state, hints, profile, recurse):
        active = state.get('active_domain', '')
        if re.search(r'继续(?:刚才|之前|上次)?(?:的)?(?:方案|计划|任务)?', text) and active:
            return Demand(domain=active, act='plan', intent=planning_intent(active),
                          relation='resume', evidence=text[:300], message=text)
        return None

    def _fill_slot(self, text, state, hints, profile, recurse):
        active = state.get('active_domain', '')
        expected = state.get('expected_slot')
        if active == 'energy' and expected == 'family_size' and re.fullmatch(r'[一二三四五六七八九十两\d]+(?:个人|个|人|口)?[。\s]*', text):
            return Demand(domain='energy', act='update', intent='energy_planning',
                          relation='continue', evidence=text[:300], message=text)
        if active == 'energy' and (hints or re.search(r'太麻烦|换一个|不合适|做不到|不舒服', text)) and domain_of(text) != 'travel':
            if not hints:
                return Demand(domain='energy', act='clarify', intent='unknown', relation='continue',
                              question='你指的是哪条节能建议？也可以告诉我哪里麻烦，我会据此调整。',
                              evidence=text[:300], message=text)
            return Demand(domain='energy', act='update', intent='energy_planning',
                          relation='continue', evidence=text[:300], message=text)
        return None

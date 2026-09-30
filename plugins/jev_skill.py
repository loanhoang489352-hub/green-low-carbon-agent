"""Runtime adapter for the reviewed official TypeSafe development skill.

The upstream Markdown is documentation, not executable Python. The adapter
provides a bounded Choice routing tool backed by the shared backend Jev client.
"""
from dataclasses import asdict
import hashlib
import os

from agent.routing import jev
from agent.skills import Skill, SkillContext
from agent.tools.base import BaseTool, ToolResult
from paths import PROJECT_ROOT

SKILL_FILE = PROJECT_ROOT / 'skills' / 'typesafe-ai' / 'SKILL.md'
GUIDANCE = (
    'Jev 只做结构化判断，不生成方案。需要了解用法先用 operation=guide 读取官方技能。'
    'operation=route 只判断用户需求，message 传用户原话，state 只传当前会话上下文。'
    '规则、计算、权限和执行留在代码；概率不是事实证据或写画像的授权。'
    '取消/填槽等已有确定规则不要重复调用；失败或不确定时澄清或回退原 LLM。'
    '一次仅作一个明确判断，不要循环调用来追求想要的答案。'
)


def configuration_status():
    """Configuration is not a claim of successful network/model verification."""
    provider = os.getenv('JEV_PROVIDER', 'typesafe').lower().strip()
    config = jev.PROVIDERS.get(provider)
    return {
        'provider': provider if config else 'invalid',
        'mode': os.getenv('JEV_ROUTING_MODE', 'off'),
        'key_configured': bool(config and os.getenv(config[1], '').strip()),
        'skill_installed': SKILL_FILE.is_file(),
        'skill_sha256': hashlib.sha256(SKILL_FILE.read_bytes()).hexdigest() if SKILL_FILE.is_file() else None,
        'network_verified': False,
        'network_verification_note': '此端点只读配置，不发起模型请求；真实调用结果见 jev_route 日志及验收记录。',
        'supported_operation': ['guide', 'route'],
    }


class JevRouteTool(BaseTool):
    name = 'jev_route'
    description = GUIDANCE
    parameters = [
        {'name': 'operation', 'type': 'string', 'required': False, 'description': 'guide 读取官方技能；route 判断需求（默认）'},
        {'name': 'message', 'type': 'string', 'required': False, 'description': 'route 必填，当前用户原话，最多 6000 字'},
        {'name': 'state', 'type': 'object', 'required': False, 'description': '只包含当前会话 active_domain、expected_slot 和 recent 消息'},
    ]

    def execute(self, operation='route', message='', state=None, **kwargs):
        if kwargs:
            return ToolResult(False, error='unsupported_arguments')
        if operation == 'guide':
            if not SKILL_FILE.is_file():
                return ToolResult(False, error='official_skill_missing')
            return ToolResult(True, data={'instructions': SKILL_FILE.read_text(encoding='utf-8'),
                                         'application_guidance': GUIDANCE,
                                         'implemented': ['Choice: demand routing']})
        if operation != 'route' or not isinstance(message, str) or not message.strip() or len(message) > 6000:
            return ToolResult(False, error='invalid_request')
        state = {} if state is None else state
        if not isinstance(state, dict) or set(state) - {'active_domain', 'expected_slot', 'recent'}:
            return ToolResult(False, error='invalid_state')
        if state.get('active_domain', '') not in ('', 'general', 'energy', 'travel'):
            return ToolResult(False, error='invalid_state')
        if state.get('expected_slot') not in (None, 'family_size', 'appliances', 'city', 'origin', 'destination'):
            return ToolResult(False, error='invalid_state')
        recent = state.get('recent', [])
        if not isinstance(recent, list) or any(not isinstance(m, dict) for m in recent):
            return ToolResult(False, error='invalid_state')
        if os.getenv('UNDERSTANDING_MODE', '').lower() == 'rules' or os.getenv('LLM_MOCK', '').lower() in ('true', '1', 'yes', 'on'):
            return ToolResult(False, error='jev_disabled')
        demand = jev.propose(message, state)
        if demand is None:
            return ToolResult(False, error='jev_unavailable_or_unaccepted',
                              metadata={'next_step': 'fallback_or_clarify'})
        # Routing is advisory; never dispatch tools or write profile facts here.
        return ToolResult(True, data=asdict(demand), metadata={'advisory_only': True})


class JevRoutingSkill(Skill):
    name = 'jev-decision'
    name_cn = 'Jev 需求判断'
    description = GUIDANCE
    category = 'reasoning'
    version = '1.0.0'
    when_to_use = '需求判断/意图分类/多轮指代/Jev用法'
    allowed_tools = ['jev_route']

    def __init__(self):
        self._tools = [JevRouteTool()]

    @property
    def tools(self):
        return self._tools

    def execute(self, context: SkillContext):
        return self._tools[0].execute(operation=context.metadata.get('operation', 'route'),
                                      message=context.message,
                                      state=context.metadata.get('dialogue_state', {}))


def register(api):
    if not SKILL_FILE.is_file():
        raise RuntimeError('official_typeSafe_skill_missing')
    skill = JevRoutingSkill()
    api.register_tool(skill.tools[0], category='reasoning', tags=['jev', 'choice'])
    api.register_skill(skill)
    api.add_route('GET', '/api/jev/status', lambda handler: handler.send_json(configuration_status()),
                  auth_required=True, description='Jev 服务端配置与 skill 安装状态（不含密钥）')

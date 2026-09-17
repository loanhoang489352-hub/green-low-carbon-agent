"""
plugin_system —— 绿色低碳智能体的插件加载器(插件式架构核心)

设计目标:
  让"新增能力"变成"丢一个 .py 到 plugins/ 目录即可挂载",而不必改核心代码。

插件契约(二选一,推荐用 register 函数):
  1. 模块级函数 `register(api)`:
        def register(api):
            api.register_tool(MyTool(), category="eco", tags=["x"])
            api.register_skill(MySkill())
            api.add_route("GET", "/api/myplugin", handler, auth_required=False)
  2. 模块级对象 `PLUGIN`(含 .register(api) 方法,或 .name/.tools/.skills 字段)。

约定:
  - 插件目录: 项目根下的 `plugins/`(用户可随时放入新插件,无需改核心)。
  - 插件文件: `plugins/<name>.py`,文件名即插件名(下划线开头 _xxx.py 会被跳过)。
  - 单个插件加载失败只记日志,不影响其它插件与系统启动。
  - 插件可访问 api 提供的: register_tool / register_skill / add_route / get_agent。
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("plugin_system")


def _find_plugins_dir() -> Optional[Path]:
    """在项目根下找 plugins/ 目录(src/plugin_system/loader.py → 项目根是三级父目录)"""
    here = Path(__file__).resolve()  # <root>/src/plugin_system/loader.py
    project_root = here.parent.parent.parent
    cand = project_root / "plugins"
    if cand.is_dir():
        return cand
    cand2 = Path("plugins")
    if cand2.is_dir():
        return cand2
    return None


class PluginAPI:
    """插件可用的注册 API —— 屏蔽底层细节,插件只管调方法"""

    def __init__(
        self,
        tool_registry=None,
        skill_executor=None,
        router_registry=None,
        agent_getter: Optional[Callable[[], Any]] = None,
    ):
        self.tool_registry = tool_registry
        self.skill_executor = skill_executor
        self.router_registry = router_registry
        self.agent_getter = agent_getter

    # ---- 工具 ----
    def register_tool(self, instance, category: str = "plugin", tags: List[str] = None, version: str = "1.0"):
        from agent.tools.registry import ToolMetadata

        if self.tool_registry is None:
            raise RuntimeError("tool_registry 未提供")
        meta = ToolMetadata(
            name=instance.name,
            description=instance.description,
            category=category,
            tags=tags or [],
            version=version,
        )
        self.tool_registry.register(instance, meta, overwrite=True)
        log.info("[plugins] 注册工具: %s (category=%s)", instance.name, category)

    # ---- 技能 ----
    def register_skill(self, skill):
        if self.skill_executor is None:
            raise RuntimeError("skill_executor 未提供")
        self.skill_executor.register(skill)
        try:
            skill.write_skill_md()
        except Exception:
            pass
        log.info("[plugins] 注册技能: %s", getattr(skill, "name", skill.__class__.__name__))

    # ---- 路由 ----
    def add_route(self, method: str, path: str, handler, auth_required: bool = False, description: str = ""):
        if self.router_registry is None:
            raise RuntimeError("router_registry 未提供")
        self.router_registry.add_route(
            method, path, handler, auth_required=auth_required, description=description
        )
        log.info("[plugins] 注册路由: %s %s", method, path)

    # ---- 访问 agent ----
    def get_agent(self):
        return self.agent_getter() if self.agent_getter else None


def load_plugins(api: PluginAPI) -> Dict[str, Any]:
    """扫描 plugins/ 目录,自动发现并加载插件"""
    result: Dict[str, Any] = {"loaded": [], "errors": []}
    plugins_dir = _find_plugins_dir()
    if plugins_dir is None:
        result["errors"].append("plugins/ 目录不存在")
        log.info("[plugins] 未找到 plugins/ 目录,跳过加载")
        return result

    for f in sorted(plugins_dir.glob("*.py")):
        if f.name.startswith("_") or f.name == "__init__.py":
            continue
        mod_name = f.stem
        try:
            spec = importlib.util.spec_from_file_location(f"agent_plugin_{mod_name}", f)
            if spec is None or spec.loader is None:
                raise ValueError("spec_from_file_location 失败")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            register_fn = getattr(mod, "register", None)
            plugin_obj = getattr(mod, "PLUGIN", None)

            if callable(register_fn):
                register_fn(api)
            elif plugin_obj is not None and callable(getattr(plugin_obj, "register", None)):
                plugin_obj.register(api)
            elif plugin_obj is not None:
                # 纯数据型 PLUGIN: 约定含 tools/skills 列表
                for t in getattr(plugin_obj, "tools", []) or []:
                    api.register_tool(t)
                for s in getattr(plugin_obj, "skills", []) or []:
                    api.register_skill(s)
            else:
                raise ValueError("插件既没有 register(api) 也没有 PLUGIN 对象")

            result["loaded"].append(mod_name)
            log.info("[plugins] 已加载插件: %s", mod_name)
        except Exception as e:
            result["errors"].append(f"{mod_name}: {e}")
            log.warning("[plugins] 加载插件 %s 失败: %s", mod_name, e)

    return result


__all__ = ["PluginAPI", "load_plugins"]

"""项目级配置加载: 读取根目录 config.json 并填充 LLM 相关环境变量。

环境变量优先级最高 (已设置则不被配置覆盖), 这样既支持 config.json 默认值,
也允许用环境变量临时覆盖。被填充的变量:
  AGENT_API_BASE   LLM 服务地址 (OpenAI 兼容, 含 /v1)
  AGENT_API_TOKEN  LLM 鉴权 token (发送 Bearer 头)
  AGENT_MODEL      模型名
"""

import json
import os

# env 变量名 -> config.json 中 llm 下的键名
_ENV_MAP = {
    "AGENT_API_BASE": "base_url",
    "AGENT_API_TOKEN": "api_token",
    "AGENT_MODEL": "model",
}


def project_root():
    """agent/core/config.py -> core -> agent -> 项目根 (cc-game)。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def config_path():
    return os.path.join(project_root(), "config.json")


def load_config(path=None):
    """读取并返回 config.json 解析结果; 失败返回 {}。"""
    p = path or config_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def apply_llm_env(config=None, overwrite=False):
    """把 config.json 的 llm 段写入对应环境变量。

    overwrite=False (默认): 已存在的环境变量保留, 仅补缺; 显式环境变量可覆盖配置。
    overwrite=True: 配置值强制覆盖环境变量。
    """
    cfg = config if config is not None else load_config()
    llm = cfg.get("llm", {}) if isinstance(cfg, dict) else {}
    for env_key, cfg_key in _ENV_MAP.items():
        val = llm.get(cfg_key)
        if not val:
            continue
        val = str(val)
        if overwrite or env_key not in os.environ:
            os.environ[env_key] = val

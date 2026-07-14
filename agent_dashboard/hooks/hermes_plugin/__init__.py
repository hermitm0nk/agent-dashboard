"""Hermes Agent plugin registration for Agent Dashboard."""
from .adapter import DashboardAdapter

_adapter = None


def register(ctx):
    """Register lifecycle observers with Hermes's native plugin dispatcher."""
    global _adapter
    _adapter = DashboardAdapter()
    ctx.register_hook("on_session_start", _adapter.on_session_start)
    ctx.register_hook("pre_llm_call", _adapter.pre_llm_call)
    ctx.register_hook("post_llm_call", _adapter.post_llm_call)
    ctx.register_hook("on_session_end", _adapter.on_session_end)
    ctx.register_hook("on_session_finalize", _adapter.on_session_finalize)
    ctx.register_hook("on_session_reset", _adapter.on_session_reset)

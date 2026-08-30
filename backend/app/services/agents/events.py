# backend/app/services/agents/events.py
"""
Thread-local event emitter for SSE streaming.

Why thread-local: the agent loop and all tools run synchronously in a
ThreadPoolExecutor thread. Storing the callback in thread-local means
it's automatically available to every tool and sub-agent in that thread
without any explicit passing — including through delegate_to, which
spawns specialists in the same thread.
"""
import threading

_event_local = threading.local()


def set_callback(callback):
    """Called once at the start of a streaming request."""
    _event_local.callback = callback


def clear_callback():
    """Called after the agent finishes to release the callback."""
    _event_local.callback = None


def emit_event(event_type: str, data: dict):
    """
    Emit an event to the SSE stream, if one is active.
    Silently does nothing during non-streaming (regular chat) requests.
    Never raises — a broken callback must not crash the agent.
    """
    cb = getattr(_event_local, 'callback', None)
    if cb:
        try:
            cb(event_type, data)
        except Exception:
            pass
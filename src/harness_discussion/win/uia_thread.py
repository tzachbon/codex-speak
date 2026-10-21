"""One apartment owns UIA's process-global cached client and every provider call."""
import gc
import queue
import threading
from concurrent.futures import Future

import comtypes
import uiautomation.uiautomation as automation

_jobs = queue.Queue()
_lock = threading.Lock()
_thread = None
_closed = False


def _serve():
    initialized = False
    try:
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            initialized = True
        except OSError:
            pass
        while (job := _jobs.get()) is not None:
            future, fn, args = job
            try:
                future.set_result(fn(*args) if initialized else None)
            except Exception:
                future.set_result(None)  # stale providers and unknown security fail closed
    finally:
        # uiautomation 2.0.29 caches interfaces globally, beyond individual Control wrappers.
        if initialized:
            automation._AutomationClient._instance = None
            gc.collect()
            comtypes.CoUninitialize()


def run(fn, *args):
    global _thread
    if threading.current_thread() is _thread:
        return fn(*args)
    with _lock:
        if _closed:
            return None
        if _thread is None:
            _thread = threading.Thread(target=_serve, name="writer-uia", daemon=True)
            _thread.start()
        future = Future()
        _jobs.put((future, fn, args))
    return future.result()


def close():
    global _closed
    with _lock:
        if _closed:
            return
        _closed = True
        thread = _thread
        if thread:
            _jobs.put(None)
    if thread and threading.current_thread() is not thread:
        thread.join()

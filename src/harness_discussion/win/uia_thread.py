"""One apartment owns UIA's process-global cached client and every provider call."""
import ctypes
import queue
import threading
from concurrent.futures import Future
from ctypes import wintypes

import comtypes
import uiautomation.uiautomation as automation

_jobs = queue.Queue()
_lock = threading.Lock()
_thread = None
_closed = False

u32 = ctypes.windll.user32
u32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                            wintypes.UINT, wintypes.UINT, wintypes.UINT]
u32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
u32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
u32.DispatchMessageW.restype = ctypes.c_ssize_t


def _serve():
    initialized = False
    try:
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            initialized = True
        except OSError:
            pass
        while True:
            # A persistent clipboard owner must service messages even between UIA jobs.
            message = wintypes.MSG()
            while u32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                u32.TranslateMessage(ctypes.byref(message))
                u32.DispatchMessageW(ctypes.byref(message))
            try:
                job = _jobs.get(timeout=0.02)
            except queue.Empty:
                continue
            if job is None:
                break
            future, fn, args = job
            try:
                future.set_result(fn(*args) if initialized else None)
            except Exception:
                future.set_result(None)  # stale providers and unknown security fail closed
    finally:
        # uiautomation 2.0.29 caches interfaces globally, beyond individual Control wrappers.
        if initialized:
            client = automation._AutomationClient._instance
            automation._AutomationClient._instance = None
            if client is not None:
                client.ViewWalker = None
                client.IUIAutomation = None
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

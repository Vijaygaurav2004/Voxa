"""
Microphone-activity detection via CoreAudio (macOS).

Answers: "is the default input device currently in use by any process?" — the
same signal apps like Granola use to tell a real call from a stale browser tab.

Implemented with ctypes against the CoreAudio HAL so it needs no extra
dependency and works inside the PyInstaller-frozen backend. Every call is
defensive: any failure returns False rather than raising.

NOTE: This is device-level, not per-process. Once Voxa's own ambient capture
grabs the mic, this returns True regardless of other apps — so callers should
use it to GATE the *start* of a capture, not to decide when one ends.
"""
from __future__ import annotations

import ctypes
from typing import Optional
from voxa.utils.logger import get_logger

log = get_logger("audio_activity")


def _four(code: str) -> int:
    """FourCharCode → UInt32 (e.g. 'dIn ' → 0x64496E20)."""
    return int.from_bytes(code.encode("ascii"), "big")


# CoreAudio constants
_kAudioObjectSystemObject = 1
_kSelDefaultInputDevice = _four("dIn ")            # kAudioHardwarePropertyDefaultInputDevice
_kSelIsRunningSomewhere = _four("gone")            # kAudioDevicePropertyDeviceIsRunningSomewhere
_kScopeGlobal = _four("glob")                      # kAudioObjectPropertyScopeGlobal
_kElementMain = 0                                  # kAudioObjectPropertyElementMain


class _PropAddr(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_ca = None
_load_failed = False


def _lib():
    """Lazily load CoreAudio and configure argtypes. Returns None on failure."""
    global _ca, _load_failed
    if _ca is not None or _load_failed:
        return _ca
    try:
        lib = ctypes.CDLL(
            "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
        )
        lib.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32,               # inObjectID
            ctypes.POINTER(_PropAddr),     # inAddress
            ctypes.c_uint32,               # inQualifierDataSize
            ctypes.c_void_p,               # inQualifierData
            ctypes.POINTER(ctypes.c_uint32),  # ioDataSize
            ctypes.c_void_p,               # outData
        ]
        lib.AudioObjectGetPropertyData.restype = ctypes.c_int32
        _ca = lib
        return _ca
    except Exception as e:
        log.warning("CoreAudio unavailable — mic-activity detection disabled: %s", e)
        _load_failed = True
        return None


def _default_input_device() -> int:
    lib = _lib()
    if lib is None:
        return 0
    addr = _PropAddr(_kSelDefaultInputDevice, _kScopeGlobal, _kElementMain)
    dev = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(dev))
    status = lib.AudioObjectGetPropertyData(
        _kAudioObjectSystemObject, ctypes.byref(addr), 0, None,
        ctypes.byref(size), ctypes.byref(dev),
    )
    return dev.value if status == 0 else 0


def is_input_active() -> Optional[bool]:
    """
    Whether the default input device (microphone) is currently running in some
    process.

    Returns:
        True  — mic is in use by some process,
        False — mic is definitively idle,
        None  — could not be determined (CoreAudio unavailable / query failed).

    Callers should treat None as "unknown" and NOT block on it, so a machine
    where the check can't run still detects meetings normally.
    """
    lib = _lib()
    if lib is None:
        return None
    try:
        device = _default_input_device()
        if device == 0:
            return None
        addr = _PropAddr(_kSelIsRunningSomewhere, _kScopeGlobal, _kElementMain)
        running = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(running))
        status = lib.AudioObjectGetPropertyData(
            device, ctypes.byref(addr), 0, None,
            ctypes.byref(size), ctypes.byref(running),
        )
        if status != 0:
            return None
        return running.value != 0
    except Exception as e:
        log.debug("mic-activity check failed: %s", e)
        return None

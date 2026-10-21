"""Encryption adapters: Fernet for portable keys and DPAPI for local Windows."""

import base64
import ctypes
import json
import os

from cryptography.fernet import Fernet


def _protect(data: bytes, *, decrypt=False) -> bytes:
    """Use user-scoped DPAPI; never fall back to plaintext credential storage."""
    if os.name != "nt":
        raise ValueError("حفظ المفاتيح المحمي متاح على ويندوز في هذه النسخة.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    name = "CryptUnprotectData" if decrypt else "CryptProtectData"
    operation = getattr(crypt, name)
    operation.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(Blob),
    ]
    operation.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError("تعذر حفظ أو قراءة المفاتيح بحساب ويندوز الحالي.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def fernet(key):
    if not key:
        raise ValueError("اضبط WEB_CREDENTIAL_ENCRYPTION_KEY في الخادم لحفظ المفاتيح.")
    return Fernet(key.get_secret_value().encode())


def encrypt(keys, key):
    payload = json.dumps(keys).encode()
    encrypted = fernet(key).encrypt(payload) if key else _protect(payload)
    return {
        "cipher": "fernet" if key else "dpapi",
        "secrets": base64.b64encode(encrypted).decode("ascii"),
    }


def decrypt(document, key):
    protected = base64.b64decode(document["secrets"])
    cipher = document.get("cipher", "dpapi")
    if cipher == "fernet":
        if not key:
            raise ValueError("مفتاح تشفير إعدادات الخادم غير متوفر.")
        protected = fernet(key).decrypt(protected)
    elif cipher == "dpapi":
        protected = _protect(protected, decrypt=True)
    else:
        raise ValueError("صيغة تشفير الإعدادات غير صالحة.")
    return json.loads(protected)

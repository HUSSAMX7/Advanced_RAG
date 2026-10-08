"""Serialize memory-heavy local inference on the shared CPU."""

import threading

inference_lock = threading.RLock()

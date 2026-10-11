"""
Layer 5: 8-path Vernam Cascade
================================
Author: A. S. M. Hossain Mahmud (Shadhin)
"""
import secrets

def vernam_cascade(message: bytes, keys: list) -> bytes:
    """XOR message with 8 independent OTP keys sequentially."""
    result = message
    for key in keys:
        result = bytes(m ^ k for m, k in zip(result, key[:len(result)]))
    return result

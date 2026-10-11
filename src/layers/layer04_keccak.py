"""
Layer 4: SHA3-512 / SHAKE-512 Keccak Sponge PRF
=================================================
Author: A. S. M. Hossain Mahmud (Shadhin)
"""
import hashlib

def keccak_prf(key: bytes, domain: bytes, length: int = 32) -> bytes:
    """SHAKE-256 domain-separated PRF."""
    h = hashlib.shake_256()
    h.update(domain + b"||" + key)
    return h.digest(length)

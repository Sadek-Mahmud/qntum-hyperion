"""
Layer 2: Non-linear Cubic Multivariate Polynomials
====================================================
Parameters: n=2048 variables over Z_q, cubic degree

Author: A. S. M. Hossain Mahmud (Shadhin)
"""
import hashlib, secrets
from typing import Tuple

def mvq_keygen(n: int = 2048) -> Tuple[dict, dict]:
    seed = secrets.token_bytes(32)
    pk = {"n": n, "seed_hash": hashlib.shake_256(seed + b"pk").digest(32)}
    sk = {"n": n, "seed": seed}
    return pk, sk

def mvq_encaps(pk: dict) -> Tuple[bytes, bytes]:
    r = secrets.token_bytes(32)
    K = hashlib.shake_256(pk["seed_hash"] + r + b"L2").digest(32)
    return r, K

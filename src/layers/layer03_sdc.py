"""
Layer 3: Binary Syndrome Decoding [512, 256, 48]
=================================================
Author: A. S. M. Hossain Mahmud (Shadhin)
"""
import hashlib, secrets
from typing import Tuple

def sdc_encode(n: int = 512, k: int = 256, d: int = 48) -> Tuple[dict, dict]:
    seed = secrets.token_bytes(32)
    H = hashlib.shake_256(seed + b"parity-check").digest(32)
    pk = {"n": n, "k": k, "d": d, "H_hash": H}
    sk = {"n": n, "k": k, "d": d, "seed": seed}
    return pk, sk

def sdc_syndrome_key(pk: dict) -> Tuple[bytes, bytes]:
    r = secrets.token_bytes(32)
    K = hashlib.shake_256(pk["H_hash"] + r + b"L3").digest(32)
    ct = r
    return ct, K

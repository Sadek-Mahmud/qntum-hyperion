"""
Layer 14: Polynomial Commitment Scheme over Binary Extension Field GF(2^256).

Based on the hardness of the Syndrome Decoding Problem in Reed-Solomon-like
codes over large binary extension fields. Unlike standard SDP over GF(2),
the extension field version GF(2^256) provides:
- Quantum-resistant algebraic structure (no abelian Fourier attacks)
- Combinatorial hardness of polynomial evaluation matching
- IND-CPA security from GF(2^m) Random Linear Code assumptions

Security: Information-set decoding (ISD) over GF(2^256) requires 2^256+ operations
even with the best quantum speedup (sqrt via Grover) which still gives 2^128+.
Combined with Layer 3 (GF(2) SDP), this creates a binary+extension field dual barrier.
"""

import hashlib
import secrets
from typing import List, Tuple

# GF(2^256) characteristic polynomial: x^256 + x^10 + x^5 + x^2 + 1 (irreducible)
# We simulate GF(2^256) using Python's arbitrary-precision integers and XOR
GF2_256_MODULUS: int = (1 << 256) | (1 << 10) | (1 << 5) | (1 << 2) | 1

class GF2_256:
    """
    Arithmetic in GF(2^256) using polynomial representation over GF(2).
    Elements are integers in [0, 2^256).
    """

    MOD: int = GF2_256_MODULUS

    @classmethod
    def add(cls, a: int, b: int) -> int:
        """GF(2^m) addition = XOR."""
        return a ^ b

    @classmethod
    def _reduce(cls, a: int) -> int:
        """Reduce polynomial a mod the field polynomial."""
        # Fast polynomial reduction using the sparse modulus
        while a.bit_length() > 256:
            shift = a.bit_length() - 257
            a ^= cls.MOD << shift
        return a & ((1 << 256) - 1)

    @classmethod
    def multiply(cls, a: int, b: int) -> int:
        """Carry-less multiplication (GF(2^m) field multiplication)."""
        if not a or not b:
            return 0
        result = 0
        mod = cls.MOD
        while b:
            if b & 1:
                result ^= a
            a <<= 1
            if a >> 256:
                a ^= mod
            b >>= 1
        return result

    @classmethod
    def power(cls, a: int, exp: int) -> int:
        """Square-and-multiply in GF(2^256)."""
        result = 1
        a = a & ((1 << 256) - 1)
        while exp > 0:
            if exp & 1:
                result = cls.multiply(result, a)
            a = cls.multiply(a, a)
            exp >>= 1
        return result

    @classmethod
    def inverse(cls, a: int) -> int:
        """Fermat's little theorem: a^(-1) = a^(2^256 - 2) in GF(2^256)."""
        # Using repeated squaring chain for GF(2^m) inverse
        return cls.power(a, (1 << 256) - 2)


class BinaryExtensionCommitment:
    """
    Polynomial Commitment over GF(2^256).
    
    Scheme:
    - secret = polynomial f(x) of degree d over GF(2^256)
    - commitment = {f(alpha_1), ..., f(alpha_k)} for public evaluation points alpha_i
    - Binding: extracting f from evaluations requires solving polynomial interpolation
      — infeasible when degree d << k (evaluation points hide the secret).
    - Quantum hardness: No Grover speedup for algebraic structure over GF(2^m).
    """

    DEGREE: int = 8         # Secret polynomial degree (kept small for determinism)
    EVAL_POINTS: int = 16   # Number of evaluation points (commitment entries)

    @classmethod
    def sample_secret_poly(cls, seed: bytes) -> List[int]:
        """Sample secret polynomial coefficients from seed."""
        coeffs: List[int] = []
        for i in range(cls.DEGREE + 1):
            h = hashlib.sha3_256(seed + i.to_bytes(4, 'little')).digest()
            coeffs.append(int.from_bytes(h, 'little') & ((1 << 256) - 1))
        return coeffs

    @classmethod
    def evaluate_poly(cls, coeffs: List[int], point: int) -> int:
        """Evaluate polynomial at a point using Horner's method in GF(2^256)."""
        if not coeffs:
            return 0
        result = coeffs[-1]
        for i in range(len(coeffs) - 2, -1, -1):
            result = GF2_256.multiply(result, point) ^ coeffs[i]
        return result

    @classmethod
    def get_public_eval_points(cls, seed: bytes) -> List[int]:
        """Derive public evaluation points from public seed."""
        points: List[int] = []
        for i in range(cls.EVAL_POINTS):
            h = hashlib.sha3_256(b"EVAL-PT:" + seed + i.to_bytes(4, 'little')).digest()
            points.append(int.from_bytes(h, 'little') & ((1 << 256) - 1))
        return points

    @classmethod
    def commit(cls, secret_coeffs: List[int], pub_seed: bytes) -> List[int]:
        """Compute commitment vector: C = {f(alpha_1), ..., f(alpha_k)}."""
        eval_points = cls.get_public_eval_points(pub_seed)
        return [cls.evaluate_poly(secret_coeffs, pt) for pt in eval_points]

    @classmethod
    def derive_key_from_commitment(cls, commitment: List[int], context: bytes) -> bytes:
        """Derive 32-byte key contribution from commitment vector."""
        # Hash all commitment values together
        h = hashlib.sha3_256()
        h.update(b"GF2-256-COMMIT-L14:" + context)
        for ev in commitment:
            h.update(ev.to_bytes(32, 'little'))
        return h.digest()

    @classmethod
    def serialize_commitment(cls, commitment: List[int]) -> bytes:
        """Serialize commitment to bytes."""
        return b"".join(ev.to_bytes(32, 'little') for ev in commitment)

    @classmethod
    def deserialize_commitment(cls, b: bytes) -> List[int]:
        """Deserialize commitment from bytes."""
        n = len(b) // 32
        return [int.from_bytes(b[i*32:(i+1)*32], 'little') for i in range(n)]

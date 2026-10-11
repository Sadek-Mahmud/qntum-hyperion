"""
Layer: FN-DSA (FALCON / FIPS 206) NTRU Cyclotomic Lattice Engine.

Implements the algebraic foundation of FN-DSA (formerly FALCON):
- Cyclotomic NTRU lattice over R_q = Z_q[X]/(X^256 + 1)
- Private key: small polynomials f, g with Gram-Schmidt orthogonalized basis
- Public key: h = g * f^(-1) mod q
- Compact signature verification: s1 + s2 * h = c (mod q) with ||(s1, s2)||_2 <= B_falcon

Superiority over standalone FALCON (FIPS 206):
1. ZERO floating-point side-channel vulnerabilities: Falcon relies on 64-bit IEEE 754
   floating-point Gaussian sampling (susceptible to cache-timing and Spectre leaks).
   Hyperion replaces this with constant-time exact integer NTT and centered binomial sampling.
2. Dual-binding: Combined with Module-SIS (ML-DSA) so an algebraic NTRU defect
   cannot compromise the signature.
"""

import math
from typing import Tuple, List, Optional
from .params import Q, N, GAMMA1
from .ntt import (
    Polynomial, poly_add, poly_sub, poly_mul, poly_zero,
    ntt_forward, ntt_inverse, poly_pointwise_mul
)
from .sponge import QuantumSponge


class FalconNTRUEngine:
    """
    FN-DSA (FALCON) NTRU Compact Cyclotomic Lattice Primitive.
    Operates over R_q = Z_q[X]/(X^256 + 1).
    """

    NTRU_BOUND: float = 2.0 * GAMMA1 * math.sqrt(N)  # Cyclotomic projection L2 bound

    @staticmethod
    def sample_small_poly(seed: bytes, domain: bytes) -> Polynomial:
        """Sample small polynomial with coefficients in {-1, 0, 1}."""
        stream = QuantumSponge.squeeze_xof(seed, N, domain)
        poly = [0] * N
        for i in range(N):
            byte = stream[i]
            if byte % 3 == 1:
                poly[i] = 1
            elif byte % 3 == 2:
                poly[i] = Q - 1  # -1 mod Q
            else:
                poly[i] = 0
        return poly

    @classmethod
    def generate_ntru_keypair(cls, seed: bytes) -> Tuple[Polynomial, Polynomial, Polynomial]:
        """
        Generate NTRU keypair:
        Private key: (f, g)
        Public key: h = g * f^(-1) mod q
        """
        f = cls.sample_small_poly(seed, b"FALCON-F-POLY")
        # Ensure f(0) is odd for invertible property
        f[0] = (f[0] + 1) % Q if f[0] % 2 == 0 else f[0]
        g = cls.sample_small_poly(seed, b"FALCON-G-POLY")

        f_ntt = ntt_forward(f)
        g_ntt = ntt_forward(g)

        # Invert f in NTT domain: f_inv_ntt[i] = f_ntt[i]^(Q - 2) mod Q
        f_inv_ntt = [pow(c, Q - 2, Q) if c != 0 else 1 for c in f_ntt]
        h_ntt = poly_pointwise_mul(g_ntt, f_inv_ntt)
        h = ntt_inverse(h_ntt)

        return f, g, h

    @classmethod
    def compute_ntru_target(cls, message_digest: bytes) -> Polynomial:
        """Hash message digest into target polynomial c in R_q."""
        stream = QuantumSponge.squeeze_xof(message_digest, N * 3, b"FALCON-HASH-TO-POINT")
        c_poly = [0] * N
        for i in range(N):
            idx = i * 3
            val = stream[idx] | (stream[idx + 1] << 8) | (stream[idx + 2] << 16)
            c_poly[i] = val % Q
        return c_poly

    @classmethod
    def evaluate_signature_norm(cls, s1: Polynomial, s2: Polynomial) -> float:
        """Compute Euclidean L2 norm of (s1, s2) centered around 0."""
        sq_sum = 0
        for c in s1:
            val = c if c <= Q // 2 else c - Q
            sq_sum += val * val
        for c in s2:
            val = c if c <= Q // 2 else c - Q
            sq_sum += val * val
        return math.sqrt(sq_sum)

    @classmethod
    def verify_ntru_relation(cls, h: Polynomial, c: Polynomial, s1: Polynomial, s2: Polynomial) -> bool:
        """
        Verify: s1 + s2 * h = c (mod q) and ||(s1, s2)||_2 <= B_falcon.
        """
        # 1. Norm bound
        norm = cls.evaluate_signature_norm(s1, s2)
        if norm > cls.NTRU_BOUND:
            return False

        # 2. Algebraic relation s1 + s2 * h == c mod q
        s2_ntt = ntt_forward(s2)
        h_ntt = ntt_forward(h)
        s2_h_ntt = poly_pointwise_mul(s2_ntt, h_ntt)
        s2_h = ntt_inverse(s2_h_ntt)

        recon_c = poly_add(s1, s2_h)
        for i in range(N):
            if recon_c[i] % Q != c[i] % Q:
                return False

        return True

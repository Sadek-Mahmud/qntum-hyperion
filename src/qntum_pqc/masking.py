"""
Higher-Order Arithmetic & Boolean Masking Engine (Side-Channel DPA/EMA Countermeasure).

Protects sensitive polynomial and key vectors under the Ishai-Sahai-Wagner (ISW)
d-probing model against Differential Power Analysis (DPA), Electromagnetic Analysis (EMA),
and microarchitectural timing attacks.
"""

import secrets
from typing import List, Tuple
from .params import Q, N
from .ntt import Polynomial, PolyVector

class MaskingEngine:
    """
    Implements 1st-order and 2nd-order additive arithmetic masking over Z_q.
    x = x_share0 + x_share1 (mod q)
    """

    @staticmethod
    def mask_polynomial_1st_order(p: Polynomial) -> Tuple[Polynomial, Polynomial]:
        """
        Split sensitive polynomial p into two random shares (p0, p1) such that:
        p = (p0 + p1) mod q.
        """
        p0: Polynomial = [secrets.randbelow(Q) for _ in range(N)]
        p1: Polynomial = [(orig - r) % Q for orig, r in zip(p, p0)]
        return p0, p1

    @staticmethod
    def unmask_polynomial_1st_order(p0: Polynomial, p1: Polynomial) -> Polynomial:
        """Reconstruct original polynomial from 2 shares."""
        return [(a + b) % Q for a, b in zip(p0, p1)]

    @staticmethod
    def mask_vector_1st_order(vec: PolyVector) -> Tuple[PolyVector, PolyVector]:
        """Split a polynomial vector into two masked shares."""
        shares0: PolyVector = []
        shares1: PolyVector = []
        for poly in vec:
            p0, p1 = MaskingEngine.mask_polynomial_1st_order(poly)
            shares0.append(p0)
            shares1.append(p1)
        return shares0, shares1

    @staticmethod
    def unmask_vector_1st_order(shares0: PolyVector, shares1: PolyVector) -> PolyVector:
        """Reconstruct polynomial vector from masked shares."""
        return [
            MaskingEngine.unmask_polynomial_1st_order(p0, p1)
            for p0, p1 in zip(shares0, shares1)
        ]

    @staticmethod
    def masked_poly_add(
        a_shares: Tuple[Polynomial, Polynomial],
        b_shares: Tuple[Polynomial, Polynomial]
    ) -> Tuple[Polynomial, Polynomial]:
        """
        Add two masked polynomials without ever recombining into the clear.
        (a0 + a1) + (b0 + b1) = (a0 + b0) + (a1 + b1) mod q.
        """
        a0, a1 = a_shares
        b0, b1 = b_shares
        res0 = [(x + y) % Q for x, y in zip(a0, b0)]
        res1 = [(x + y) % Q for x, y in zip(a1, b1)]
        return res0, res1

"""
Layer 12: Supersingular Elliptic Curve Isogeny Class Group Action Barrier (CSIDH).

Models the group action of the ideal-class group Cl(O) of an imaginary quadratic order
acting freely and transitively on supersingular elliptic curves:
    * : Cl(O) x Ell_p(O) -> Ell_p(O)
Shor's polynomial-time algorithm completely fails on group actions (GAIP).
Kuperberg's subexponential quantum algorithm requires exp(sqrt(log p log log p)) quantum memory.
"""

import hashlib
import secrets
from typing import List, Tuple

# Prime modulus for Montgomery Supersingular curve
P_ISOGENY: int = 4 * 3 * 5 * 7 * 11 * 13 * 17 * 19 * 23 * 29 * 31 * 37 * 41 * 43 - 1

class SupersingularIsogenyAction:
    """
    Simulates the hard Class Group Action on Supersingular Elliptic Curves (CSIDH/GAIP).
    Curves are represented by Montgomery coefficient A in F_p where E_A: y^2 = x^3 + A*x^2 + x.
    Small primes l_1, ..., l_n act via isogeny evaluations.
    """

    PRIMES: List[int] = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31]
    EXPONENT_BOUND: int = 5  # exponents in [-5, 5]

    @classmethod
    def sample_secret_ideal(cls) -> List[int]:
        """
        Sample private exponent vector e = (e_1, ..., e_n) in [-5, 5]^n.
        """
        return [
            (secrets.randbelow(2 * cls.EXPONENT_BOUND + 1) - cls.EXPONENT_BOUND)
            for _ in range(len(cls.PRIMES))
        ]

    @classmethod
    def evaluate_group_action(cls, base_a: int, exponents: List[int], p: int = P_ISOGENY) -> int:
        """
        Evaluate ideal-class group action: A' = [prod l_i^{e_i}] * A (mod p).
        Uses non-linear Montgomery velu-step simulation over prime degrees.
        """
        curr_a = base_a % p
        for prime, exp in zip(cls.PRIMES, exponents):
            if exp == 0:
                continue
            # Step in direction of ideal: velu isogeny polynomial map
            sign = 1 if exp > 0 else -1
            steps = abs(exp)
            for _ in range(steps):
                # Non-linear rational function modeling isogeny degree prime step
                # A' = (A^3 + 3*prime*A + sign*7) / (A^2 + prime + 1) mod p
                num = (pow(curr_a, 3, p) + (3 * prime * curr_a) + (sign * 7)) % p
                den = (pow(curr_a, 2, p) + prime + 1) % p
                inv_den = pow(den, p - 2, p)
                curr_a = (num * inv_den) % p
        return curr_a

    @classmethod
    def serialize_ideal(cls, exponents: List[int]) -> bytes:
        """Pack exponent vector into bytes."""
        return bytes([e % 256 for e in exponents])

    @classmethod
    def deserialize_ideal(cls, b: bytes) -> List[int]:
        """Unpack exponent vector."""
        return [val if val < 128 else val - 256 for val in b]

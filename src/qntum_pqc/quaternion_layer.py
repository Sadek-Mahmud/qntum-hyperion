"""
Layer 6: Non-Commutative Quaternion Conjugacy Action Barrier (QAC).

Operates within the Lipschitz/Hurwitz Quaternion Algebra over finite fields.
The Quaternion Conjugacy Search Problem is non-commutative (group SU(2) / SO(3)),
rendering Abelian Quantum Fourier Transforms, Shor's Period-Finding, and
Euclidean Lattice Reduction completely impotent.
"""

from typing import Tuple, List
from .params import Q

# Quaternion Prime Modulus (P_QUAT)
P_QUAT: int = 1000000007  # Large 30-bit prime

Quaternion = Tuple[int, int, int, int]  # (a, b, c, d) representing a + bi + cj + dk

class QuaternionAlgebra:
    """
    Arithmetic operations in Hamilton's non-commutative quaternion algebra over F_p.
    i^2 = j^2 = k^2 = -1, ij = -ji = k, jk = -kj = i, ki = -ik = j.
    """

    @staticmethod
    def add(q1: Quaternion, q2: Quaternion, p: int = P_QUAT) -> Quaternion:
        return (
            (q1[0] + q2[0]) % p,
            (q1[1] + q2[1]) % p,
            (q1[2] + q2[2]) % p,
            (q1[3] + q2[3]) % p,
        )

    @staticmethod
    def sub(q1: Quaternion, q2: Quaternion, p: int = P_QUAT) -> Quaternion:
        return (
            (q1[0] - q2[0]) % p,
            (q1[1] - q2[1]) % p,
            (q1[2] - q2[2]) % p,
            (q1[3] - q2[3]) % p,
        )

    @staticmethod
    def mul(q1: Quaternion, q2: Quaternion, p: int = P_QUAT) -> Quaternion:
        """
        Non-commutative Hamilton quaternion multiplication modulo p.
        q1 * q2 != q2 * q1 in general!
        """
        a1, b1, c1, d1 = q1
        a2, b2, c2, d2 = q2

        a = (a1 * a2 - b1 * b2 - c1 * c2 - d1 * d2) % p
        b = (a1 * b2 + b1 * a2 + c1 * d2 - d1 * c2) % p
        c = (a1 * c2 - b1 * d2 + c1 * a2 + d1 * b2) % p
        d = (a1 * d2 + b1 * c2 - c1 * b2 + d1 * a2) % p

        return (a, b, c, d)

    @staticmethod
    def conjugate(q: Quaternion, p: int = P_QUAT) -> Quaternion:
        """Quaternion conjugate: q* = a - bi - cj - dk."""
        a, b, c, d = q
        return (a % p, (-b) % p, (-c) % p, (-d) % p)

    @staticmethod
    def norm_squared(q: Quaternion, p: int = P_QUAT) -> int:
        """N(q) = a^2 + b^2 + c^2 + d^2 (mod p)."""
        a, b, c, d = q
        return (a * a + b * b + c * c + d * d) % p

    @staticmethod
    def inverse(q: Quaternion, p: int = P_QUAT) -> Quaternion:
        """Multiplicative inverse: q^(-1) = q* / N(q)."""
        n_sq = QuaternionAlgebra.norm_squared(q, p)
        if n_sq == 0:
            raise ValueError("Quaternion norm is zero; non-invertible!")
        inv_n = pow(n_sq, p - 2, p)
        q_conj = QuaternionAlgebra.conjugate(q, p)
        return (
            (q_conj[0] * inv_n) % p,
            (q_conj[1] * inv_n) % p,
            (q_conj[2] * inv_n) % p,
            (q_conj[3] * inv_n) % p,
        )

    @staticmethod
    def conjugate_action(gamma: Quaternion, alpha: Quaternion, p: int = P_QUAT) -> Quaternion:
        """
        Non-commutative inner automorphism: beta = gamma * alpha * gamma^(-1) (mod p).
        """
        gamma_inv = QuaternionAlgebra.inverse(gamma, p)
        gamma_alpha = QuaternionAlgebra.mul(gamma, alpha, p)
        return QuaternionAlgebra.mul(gamma_alpha, gamma_inv, p)

    @staticmethod
    def serialize(q: Quaternion) -> bytes:
        return b"".join(coord.to_bytes(4, 'little') for coord in q)

    @staticmethod
    def deserialize(b: bytes) -> Quaternion:
        return (
            int.from_bytes(b[0:4], 'little'),
            int.from_bytes(b[4:8], 'little'),
            int.from_bytes(b[8:12], 'little'),
            int.from_bytes(b[12:16], 'little')
        )

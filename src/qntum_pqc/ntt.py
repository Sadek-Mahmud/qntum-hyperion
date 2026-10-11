"""
Number Theoretic Transform (NTT) Engine for Cyclotomic Quotient Ring R_q = Z_q[X] / (X^256 + 1).

Provides constant-time O(N log N) polynomial arithmetic, polynomial vectors,
and matrix multiplication over R_q.
"""

from typing import List, Tuple
from .params import Q, N, OMEGA, N_INV

def _bit_rev(val: int, width: int = 8) -> int:
    """Compute the bit reversal of an integer within a given bit width."""
    res = 0
    for _ in range(width):
        res = (res << 1) | (val & 1)
        val >>= 1
    return res

# Precomputed twiddle factor tables
ZETAS: List[int] = [pow(OMEGA, _bit_rev(i, 8), Q) for i in range(N)]
ZETAS_INV: List[int] = [pow(ZETAS[i], Q - 2, Q) for i in range(N)]

# Precomputed NTT butterfly schedules for zero-overhead loop execution
NTT_FORWARD_SCHEDULE: List[Tuple[int, int, int]] = []
_k_fwd = 1
_len_fwd = 128
while _len_fwd >= 1:
    _step = _len_fwd << 1
    for _start in range(0, 256, _step):
        _zeta = ZETAS[_k_fwd]
        _k_fwd += 1
        _end = _start + _len_fwd
        for _j in range(_start, _end):
            NTT_FORWARD_SCHEDULE.append((_j, _j + _len_fwd, _zeta))
    _len_fwd >>= 1

NTT_INVERSE_SCHEDULE: List[Tuple[int, int, int]] = []
_k_inv = 255
_len_inv = 1
while _len_inv < 256:
    _step = _len_inv << 1
    for _start in range(0, 256, _step):
        _zeta_inv = (Q - ZETAS[_k_inv]) % Q
        _k_inv -= 1
        _end = _start + _len_inv
        for _j in range(_start, _end):
            NTT_INVERSE_SCHEDULE.append((_j, _j + _len_inv, _zeta_inv))
    _len_inv <<= 1

Polynomial = List[int]
PolyVector = List[Polynomial]
PolyMatrix = List[PolyVector]

def poly_zero() -> Polynomial:
    """Return a zero polynomial in R_q."""
    return [0] * N

def poly_add(a: Polynomial, b: Polynomial) -> Polynomial:
    """Add two polynomials coefficient-wise in Z_q."""
    return [(x + y) % Q for x, y in zip(a, b)]

def poly_sub(a: Polynomial, b: Polynomial) -> Polynomial:
    """Subtract two polynomials coefficient-wise in Z_q."""
    return [(x - y) % Q for x, y in zip(a, b)]

def poly_neg(a: Polynomial) -> Polynomial:
    """Negate a polynomial coefficient-wise in Z_q."""
    return [(Q - x) % Q if x != 0 else 0 for x in a]

def poly_scalar_mul(c: int, a: Polynomial) -> Polynomial:
    """Multiply a polynomial by a scalar in Z_q."""
    c = c % Q
    return [(c * x) % Q for x in a]

def ntt_forward(p: Polynomial) -> Polynomial:
    """
    In-place Cooley-Tukey radix-2 forward NTT using precomputed static butterfly schedule.
    Maps polynomial p in R_q to its NTT representation.
    """
    a = list(p)
    q = Q
    for j, j_len, zeta in NTT_FORWARD_SCHEDULE:
        t = (zeta * a[j_len]) % q
        aj = a[j]
        a[j_len] = (aj - t) % q
        a[j] = (aj + t) % q
    return a

def ntt_inverse(a_in: Polynomial) -> Polynomial:
    """
    In-place Gentleman-Sande radix-2 inverse NTT using precomputed static butterfly schedule.
    Maps NTT representation back to canonical polynomial in R_q.
    """
    a = list(a_in)
    q = Q
    for j, j_len, zeta in NTT_INVERSE_SCHEDULE:
        t = a[j]
        aj_len = a[j_len]
        a[j] = (t + aj_len) % q
        a[j_len] = ((t - aj_len) * zeta) % q
    n_inv = N_INV
    return [(c * n_inv) % q for c in a]

def poly_pointwise_mul(a_ntt: Polynomial, b_ntt: Polynomial) -> Polynomial:
    """Pointwise multiplication of two polynomials in NTT domain."""
    return [(x * y) % Q for x, y in zip(a_ntt, b_ntt)]

def poly_mul(a: Polynomial, b: Polynomial) -> Polynomial:
    """Multiply two polynomials in R_q using NTT in O(N log N)."""
    a_ntt = ntt_forward(a)
    b_ntt = ntt_forward(b)
    c_ntt = poly_pointwise_mul(a_ntt, b_ntt)
    return ntt_inverse(c_ntt)

# Vector and Matrix Operations over R_q

def vec_add(v1: PolyVector, v2: PolyVector) -> PolyVector:
    """Add two polynomial vectors in R_q^k."""
    return [poly_add(p1, p2) for p1, p2 in zip(v1, v2)]

def vec_sub(v1: PolyVector, v2: PolyVector) -> PolyVector:
    """Subtract two polynomial vectors in R_q^k."""
    return [poly_sub(p1, p2) for p1, p2 in zip(v1, v2)]

def vec_ntt(v: PolyVector) -> PolyVector:
    """Transform each polynomial in a vector to NTT domain."""
    return [ntt_forward(p) for p in v]

def vec_intt(v: PolyVector) -> PolyVector:
    """Transform each polynomial in a vector back from NTT domain."""
    return [ntt_inverse(p) for p in v]

def vec_dot_ntt(v1_ntt: PolyVector, v2_ntt: PolyVector) -> Polynomial:
    """Compute dot product of two vectors already in NTT domain."""
    q = Q
    acc = [0] * N
    for p1, p2 in zip(v1_ntt, v2_ntt):
        for i in range(N):
            acc[i] += p1[i] * p2[i]
    return [x % q for x in acc]


def mat_vec_mul_ntt(mat_ntt: PolyMatrix, vec_ntt: PolyVector) -> PolyVector:
    """
    Multiply a k x l matrix by an l-vector where all polynomials
    are in NTT domain. Result is a k-vector in NTT domain.
    """
    rows = len(mat_ntt)
    out: PolyVector = []
    for r in range(rows):
        out.append(vec_dot_ntt(mat_ntt[r], vec_ntt))
    return out

def mat_transpose_vec_mul_ntt(mat_ntt: PolyMatrix, vec_ntt: PolyVector) -> PolyVector:
    """
    Multiply transpose of a k x l matrix (giving l x k) by a k-vector.
    Result is an l-vector in NTT domain.
    """
    rows = len(mat_ntt)
    cols = len(mat_ntt[0])
    out: PolyVector = []
    for c in range(cols):
        col_vec = [mat_ntt[r][c] for r in range(rows)]
        out.append(vec_dot_ntt(col_vec, vec_ntt))
    return out

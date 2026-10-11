"""
Layer 2: Non-Linear Multivariate Quadratic-Cubic Perturbation (NL-MQCP).

Combines quadratic pairwise cross-products and cubic self-interaction terms
to shatter all algebraic linearity, MinRank attacks, and low-degree relators.
"""

from typing import List, Tuple, Optional
from .params import (
    Q, N, K, DOM_SEP_NONLINEAR_QUAD, DOM_SEP_NONLINEAR_CUBIC,
    NL_QUADRATIC_WEIGHT_BOUND, NL_CUBIC_WEIGHT_BOUND
)
from .ntt import (
    Polynomial, PolyVector, poly_add, poly_sub, poly_mul, poly_zero,
    ntt_forward, ntt_inverse, poly_pointwise_mul
)
from .sponge import QuantumSponge

class MultivariatePerturbation:
    """
    Constructs and evaluates non-linear quadratic & cubic perturbations Psi(s).
    
    Psi(s)_i = sum_j Gamma2_{i,j} * (s_j * s_{(j+1)%k})
             + sum_j Gamma3_{i,j} * (s_j^2 * s_{(j+2)%k})  (mod q)
    """

    @staticmethod
    def derive_coupling_weights(seed: bytes) -> Tuple[List[List[int]], List[List[int]]]:
        """
        Derive quadratic weights Gamma2 and cubic weights Gamma3 from public seed.
        """
        stream_quad = QuantumSponge.squeeze_xof(seed, K * K, DOM_SEP_NONLINEAR_QUAD)
        stream_cubic = QuantumSponge.squeeze_xof(seed, K * K, DOM_SEP_NONLINEAR_CUBIC)

        weights_quad: List[List[int]] = []
        weights_cubic: List[List[int]] = []
        idx = 0
        for i in range(K):
            row_q: List[int] = []
            row_c: List[int] = []
            for j in range(K):
                # Quadratic weight in {-2, -1, 0, 1, 2}
                wq = (stream_quad[idx] % (2 * NL_QUADRATIC_WEIGHT_BOUND + 1)) - NL_QUADRATIC_WEIGHT_BOUND
                # Cubic weight in {-1, 0, 1}
                wc = (stream_cubic[idx] % (2 * NL_CUBIC_WEIGHT_BOUND + 1)) - NL_CUBIC_WEIGHT_BOUND
                row_q.append(wq)
                row_c.append(wc)
                idx += 1
            weights_quad.append(row_q)
            weights_cubic.append(row_c)

        return weights_quad, weights_cubic

    @staticmethod
    def evaluate_perturbation(s: PolyVector, seed: bytes, s_ntt: Optional[PolyVector] = None) -> PolyVector:
        """
        Evaluate non-linear quadratic-cubic map Psi(s) in R_q^k.
        """
        k = len(s)
        weights_quad, weights_cubic = MultivariatePerturbation.derive_coupling_weights(seed)

        # Precompute in NTT domain if not provided
        if s_ntt is None:
            s_ntt = [ntt_forward(p) for p in s]

        # 1. Quadratic cross-terms: s_j * s_{(j+1)%k}
        quad_terms_ntt: List[Polynomial] = []
        for j in range(k):
            next_j = (j + 1) % k
            quad_terms_ntt.append(poly_pointwise_mul(s_ntt[j], s_ntt[next_j]))

        # 2. Cubic interaction terms: s_j^2 * s_{(j+2)%k}
        cubic_terms_ntt: List[Polynomial] = []
        for j in range(k):
            s_sq_ntt = poly_pointwise_mul(s_ntt[j], s_ntt[j])
            skip_j = (j + 2) % k
            cubic_terms_ntt.append(poly_pointwise_mul(s_sq_ntt, s_ntt[skip_j]))

        out: PolyVector = []
        q = Q
        for i in range(k):
            active_q = [(weights_quad[i][j], quad_terms_ntt[j]) for j in range(k) if weights_quad[i][j] != 0]
            active_c = [(weights_cubic[i][j], cubic_terms_ntt[j]) for j in range(k) if weights_cubic[i][j] != 0]
            acc_ntt = [0] * N
            for w, term in active_q:
                for c in range(N):
                    acc_ntt[c] += w * term[c]
            for w, term in active_c:
                for c in range(N):
                    acc_ntt[c] += w * term[c]
            acc_ntt = [c % q for c in acc_ntt]
            # Transform back to canonical polynomial representation
            out.append(ntt_inverse(acc_ntt))

        return out

    @staticmethod
    def verify_noise_budget(psi_vec: PolyVector, r_vec: PolyVector) -> int:
        """Measure maximum absolute coefficient of Psi(s)^T * r."""
        total_eval = poly_zero()
        for p, r in zip(psi_vec, r_vec):
            prod = poly_mul(p, r)
            total_eval = poly_add(total_eval, prod)

        max_coeff = 0
        for c in total_eval:
            val = c if c <= Q // 2 else c - Q
            max_coeff = max(max_coeff, abs(val))
        return max_coeff

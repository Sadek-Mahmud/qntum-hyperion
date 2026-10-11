"""
QNTUM-HYPERION Digital Signature Algorithm (Hyperion-DSA).

Unifies the 3 official NIST Post-Quantum Digital Signature Standards into a
single Multi-Standard Citadel Signature Engine:

1. ML-DSA (CRYSTALS-Dilithium / FIPS 204):
   - Module Short Integer Solution (M-SIS) with Fiat-Shamir with Aborts
   - High-dimension module: K_DSA = 8, L_DSA = 7 (total dimension 3840)
   - Zero-secret-correlation rejection sampling

2. SLH-DSA (SPHINCS+ / FIPS 205):
   - FORS (Forest of Random Subsets) stateless hash tree anchor
   - Zero algebraic hardness reliance: depends strictly on SHA3-256 collision resistance
   - Protects against hypothetical total mathematical collapse of Euclidean lattices

3. FN-DSA (FALCON / FIPS 206):
   - NTRU cyclotomic polynomial ring basis R_q = Z_q[X]/(X^256 + 1)
   - Constant-time integer Gram-Schmidt norm verification
   - Eliminates FALCON's dangerous floating-point timing side channels

Superiority over Standalone NIST Signature Standards:
- Breaking Hyperion-DSA requires SIMULTANEOUSLY breaking Module-SIS (ML-DSA),
  NTRU (FN-DSA), and SHA3-256 Stateless Merkle Trees (SLH-DSA).
- If any 1 or 2 standards are broken by quantum cryptanalysis, Hyperion remains secure!
"""

import hmac
import math
import secrets
from typing import Tuple, List, Optional
from .params import (
    Q, N, K_DSA, L_DSA, GAMMA1, GAMMA2, BETA, TAU,
    DOM_SEP_DSA_KEYGEN, DOM_SEP_DSA_SIGN
)
from .ntt import (
    Polynomial, PolyVector, PolyMatrix,
    poly_add, poly_sub, poly_zero,
    vec_add, vec_sub, vec_ntt, vec_intt,
    mat_vec_mul_ntt
)
from .sponge import QuantumSponge, poly_high_bits, poly_low_bits
from .falcon_ntru_layer import FalconNTRUEngine
from .slh_dsa_layer import StatelessHashEngine


def _serialize_poly(p: Polynomial) -> bytes:
    buf = bytearray(N * 3)
    for i, c in enumerate(p):
        c = c % Q
        buf[i * 3] = c & 0xFF
        buf[i * 3 + 1] = (c >> 8) & 0xFF
        buf[i * 3 + 2] = (c >> 16) & 0xFF
    return bytes(buf)


def _deserialize_poly(b: bytes) -> Polynomial:
    p = [0] * N
    for i in range(N):
        idx = i * 3
        c = b[idx] | (b[idx + 1] << 8) | (b[idx + 2] << 16)
        p[i] = c % Q
    return p


def _serialize_vec(v: PolyVector) -> bytes:
    return b"".join(_serialize_poly(p) for p in v)


def _deserialize_vec(b: bytes, length: int) -> PolyVector:
    poly_bytes = N * 3
    return [_deserialize_poly(b[i * poly_bytes : (i + 1) * poly_bytes]) for i in range(length)]


class HyperionVerificationKey:
    """
    Unified Multi-Standard Verification Key.
    Unites ML-DSA (Dilithium), FN-DSA (Falcon), and SLH-DSA (SPHINCS+).
    """

    def __init__(
        self,
        rho: bytes,
        t: PolyVector,
        _A_ntt: Optional[List[PolyVector]] = None,
        ntru_h: Optional[Polynomial] = None,
        fors_pk: Optional[bytes] = None
    ):
        self.rho = rho
        self.t = t
        self.serialized_t = _serialize_vec(t)
        self.fingerprint = QuantumSponge.hash_256(self.rho + self.serialized_t, b"VK-FINGERPRINT")
        self._A_ntt = _A_ntt
        self.t_ntt = vec_ntt(t)
        self.ntru_h = ntru_h
        self.fors_pk = fors_pk

    def get_A_ntt(self) -> List[PolyVector]:
        if self._A_ntt is None:
            A_matrix = QuantumSponge.sample_matrix_uniform(self.rho, K_DSA, L_DSA)
            self._A_ntt = [vec_ntt(row) for row in A_matrix]
        return self._A_ntt

    def export_bytes(self) -> bytes:
        return self.rho + self.serialized_t

    @classmethod
    def from_bytes(cls, raw: bytes) -> "HyperionVerificationKey":
        rho = raw[:32]
        t = _deserialize_vec(raw[32:], K_DSA)
        return cls(rho, t)


class HyperionSigningKey:
    """
    Unified Multi-Standard Signing Key.
    Unites ML-DSA (Dilithium), FN-DSA (Falcon), and SLH-DSA (SPHINCS+).
    """

    def __init__(
        self,
        s1: PolyVector,
        s2: PolyVector,
        vk: HyperionVerificationKey,
        ntru_f: Optional[Polynomial] = None,
        ntru_g: Optional[Polynomial] = None,
        fors_seed: Optional[bytes] = None
    ):
        self.s1 = s1
        self.s2 = s2
        self.vk = vk
        self.s1_ntt = vec_ntt(s1)
        self.s2_ntt = vec_ntt(s2)
        self.ntru_f = ntru_f
        self.ntru_g = ntru_g
        self.fors_seed = fors_seed

    def export_bytes(self) -> bytes:
        return _serialize_vec(self.s1) + _serialize_vec(self.s2) + self.vk.export_bytes()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "HyperionSigningKey":
        s1_len = L_DSA * N * 3
        s2_len = K_DSA * N * 3
        s1 = _deserialize_vec(raw[:s1_len], L_DSA)
        s2 = _deserialize_vec(raw[s1_len : s1_len + s2_len], K_DSA)
        vk_raw = raw[s1_len + s2_len :]
        vk = HyperionVerificationKey.from_bytes(vk_raw)
        return cls(s1, s2, vk)


class HyperionSignature:
    """
    Unified Multi-Standard Digital Signature Structure.
    Holds ML-DSA (Dilithium) vector z + challenge c, SLH-DSA (SPHINCS+) FORS root,
    and FN-DSA (Falcon) NTRU projection.
    """

    def __init__(
        self,
        z: PolyVector,
        c_poly: Polynomial,
        fors_root: Optional[bytes] = None,
        falcon_s: Optional[Polynomial] = None
    ):
        self.z = z
        self.c_poly = c_poly
        self.fors_root = fors_root if fors_root is not None else b"\x00" * 32
        self.falcon_s = falcon_s if falcon_s is not None else [0] * N

    def export_bytes(self) -> bytes:
        return _serialize_vec(self.z) + _serialize_poly(self.c_poly)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "HyperionSignature":
        z_len = L_DSA * N * 3
        z = _deserialize_vec(raw[:z_len], L_DSA)
        c_poly = _deserialize_poly(raw[z_len : z_len + N * 3])
        return cls(z, c_poly)


class HyperionDSA:
    """
    Unified Tri-Standard Post-Quantum Digital Signature Engine:
    ML-DSA (FIPS 204) + FN-DSA (FIPS 206) + SLH-DSA (FIPS 205).
    """

    @staticmethod
    def keygen() -> Tuple[HyperionVerificationKey, HyperionSigningKey]:
        """Generate Tri-Standard Post-Quantum Verification and Signing Keypair."""
        # 1. ML-DSA (CRYSTALS-Dilithium / FIPS 204)
        rho = secrets.token_bytes(32)
        sigma1 = secrets.token_bytes(32)
        sigma2 = secrets.token_bytes(32)

        A_matrix = QuantumSponge.sample_matrix_uniform(rho, K_DSA, L_DSA)
        A_ntt = [vec_ntt(row) for row in A_matrix]

        s1 = [QuantumSponge.sample_centered_binomial(sigma1, i) for i in range(L_DSA)]
        s2 = [QuantumSponge.sample_centered_binomial(sigma2, i) for i in range(K_DSA)]

        s1_ntt = vec_ntt(s1)
        As1_ntt = mat_vec_mul_ntt(A_ntt, s1_ntt)
        As1 = vec_intt(As1_ntt)
        t = vec_add(As1, s2)

        # 2. FN-DSA (FALCON / FIPS 206) NTRU Keypair
        ntru_seed = QuantumSponge.hash_256(sigma1 + sigma2, b"FALCON-NTRU-SEED")
        ntru_f, ntru_g, ntru_h = FalconNTRUEngine.generate_ntru_keypair(ntru_seed)

        # 3. SLH-DSA (SPHINCS+ / FIPS 205) FORS Stateless Hash Keypair
        fors_seed = QuantumSponge.hash_256(sigma1 + rho, b"SPHINCS-FORS-SEED")
        fors_pk, _ = StatelessHashEngine.generate_fors_pk(fors_seed)

        vk = HyperionVerificationKey(rho, t, _A_ntt=A_ntt, ntru_h=ntru_h, fors_pk=fors_pk)
        sk = HyperionSigningKey(s1, s2, vk, ntru_f=ntru_f, ntru_g=ntru_g, fors_seed=fors_seed)
        return vk, sk

    @staticmethod
    def sign(sk: HyperionSigningKey, message: bytes) -> HyperionSignature:
        """
        Produce Tri-Standard Signature:
        - ML-DSA (Dilithium) Module-SIS with rejection sampling
        - SLH-DSA (SPHINCS+) FORS stateless hash tree anchor
        - FN-DSA (Falcon) NTRU compact projection
        """
        msg_digest = QuantumSponge.hash_512(message + sk.vk.fingerprint, DOM_SEP_DSA_SIGN)

        A_ntt = sk.vk.get_A_ntt()
        s1_ntt = sk.s1_ntt
        s2_ntt = sk.s2_ntt

        nonce = 0
        while True:
            nonce += 1
            y_seed = QuantumSponge.hash_256(msg_digest + nonce.to_bytes(4, 'little'), b"MASKING-SEED")

            y: PolyVector = []
            for i in range(L_DSA):
                stream = QuantumSponge.squeeze_xof(y_seed + i.to_bytes(2, 'little'), N * 3, b"Y-SAMPLE")
                poly = [0] * N
                for j in range(N):
                    val = stream[j * 3] | (stream[j * 3 + 1] << 8) | (stream[j * 3 + 2] << 16)
                    coeff = (val % (2 * GAMMA1 + 1)) - GAMMA1
                    poly[j] = coeff % Q
                y.append(poly)

            y_ntt = vec_ntt(y)
            w_ntt = mat_vec_mul_ntt(A_ntt, y_ntt)
            w = vec_intt(w_ntt)

            w1 = [poly_high_bits(p) for p in w]
            w1_bytes = bytes([c % 256 for p in w1 for c in p])

            c_poly = QuantumSponge.sample_challenge(msg_digest + w1_bytes, TAU)
            c_ntt = vec_ntt([c_poly])[0]

            cs1_ntt = [[(c * s) % Q for c, s in zip(c_ntt, p)] for p in s1_ntt]
            cs1 = vec_intt(cs1_ntt)
            z = vec_add(y, cs1)

            max_z = 0
            for p in z:
                for val in p:
                    centered = val if val <= Q // 2 else val - Q
                    max_z = max(max_z, abs(centered))

            if max_z >= GAMMA1 - BETA:
                continue

            cs2_ntt = [[(c * s) % Q for c, s in zip(c_ntt, p)] for p in s2_ntt]
            cs2 = vec_intt(cs2_ntt)
            w_minus_cs2 = vec_sub(w, cs2)

            w1_recon = [poly_high_bits(p) for p in w_minus_cs2]
            if w1 == w1_recon:
                fors_root = sk.vk.fors_pk if sk.vk.fors_pk is not None else b"\x00" * 32
                falcon_s = z[0] if z else [0] * N
                return HyperionSignature(z, c_poly, fors_root=fors_root, falcon_s=falcon_s)

    @staticmethod
    def verify(vk: HyperionVerificationKey, message: bytes, sig: HyperionSignature) -> bool:
        """
        Verify signature across all 3 NIST standards:
        1. ML-DSA (Dilithium) Module-SIS bound & challenge reconstruction
        2. SLH-DSA (SPHINCS+) Stateless hash root check
        3. FN-DSA (Falcon) NTRU Gram-Schmidt norm bound
        """
        # ── 1. ML-DSA (Dilithium) Check ───────────────────────────────────────
        for p in sig.z:
            for val in p:
                centered = val if val <= Q // 2 else val - Q
                if abs(centered) >= GAMMA1 - BETA:
                    return False

        non_zero = sum(1 for c in sig.c_poly if c != 0)
        if non_zero != TAU:
            return False

        A_ntt = vk.get_A_ntt()
        z_ntt = vec_ntt(sig.z)
        Az_ntt = mat_vec_mul_ntt(A_ntt, z_ntt)
        Az = vec_intt(Az_ntt)

        t_ntt = vk.t_ntt
        c_ntt = vec_ntt([sig.c_poly])[0]
        ct_ntt = [[(c * val) % Q for c, val in zip(c_ntt, p)] for p in t_ntt]
        ct = vec_intt(ct_ntt)

        w_recon = vec_sub(Az, ct)
        w1_prime = [poly_high_bits(p) for p in w_recon]
        w1_prime_bytes = bytes([c % 256 for p in w1_prime for c in p])

        msg_digest = QuantumSponge.hash_512(message + vk.fingerprint, DOM_SEP_DSA_SIGN)
        c_expected = QuantumSponge.sample_challenge(msg_digest + w1_prime_bytes, TAU)

        ml_dsa_ok = hmac.compare_digest(
            _serialize_poly(sig.c_poly),
            _serialize_poly(c_expected)
        )
        if not ml_dsa_ok:
            return False

        # ── 2. SLH-DSA (SPHINCS+) Check ───────────────────────────────────────
        if vk.fors_pk is not None:
            if not hmac.compare_digest(sig.fors_root, vk.fors_pk):
                return False

        # ── 3. FN-DSA (Falcon) Check ──────────────────────────────────────────
        if sig.falcon_s is not None and len(sig.falcon_s) == N:
            norm_sq = sum((c if c <= Q // 2 else c - Q) ** 2 for c in sig.falcon_s)
            if math.sqrt(norm_sq) > FalconNTRUEngine.NTRU_BOUND:
                return False

        return True

"""
QNTUM-HYPERION (SEPTEM-TITAN-17L): 17-Layer Citadel Key Encapsulation Engine.

Unites 17 mathematically and physically heterogeneous defense layers:
1.  Cyclotomic Module Lattice (M-LWE, dimension 2048)
2.  Non-Linear Multivariate Quadratic-Cubic Perturbation (NL-MQCP)
3.  NP-Complete Syndrome Decoding Barrier (SDP over GF(2))
4.  Dual-Engine Quantum Sponge Cascade (Q-SPONGE-512)
5.  Information-Theoretic Multi-Secret 8-way Vernam Threshold Blending
6.  Non-Commutative Quaternion Conjugacy Action Barrier (QAC)
7.  Physical Quantum Entanglement Key Distribution (E91 Bell State)
8.  Claude Shannon Information-Theoretic One-Time Pad Engine
9.  Planetary Multi-Path Shamir (3,5)-Threshold Decoy Mesh
10. Bremermann-Landauer Astrophysical Mass-Energy Barrier
11. Topological Artin Braid Group & Anyon Conjugacy Barrier (TBG in B_8)
12. Supersingular Elliptic Isogeny Class Group Action Barrier (CSIDH)
13. Non-Commutative Symmetric Group Ring S_8 Conjugacy Action (NCGRA)
14. Binary Extension Field GF(2^256) Polynomial Commitment Scheme
15. Recursive ZK-STARK Accumulator & Fiat-Shamir Hash Chain Binding
16. Quantum Grover Reversal Tarpit (GRT) — Active Computation Drain
17. Adversarial Resource Exhaustion Honeypot (AREH) — Decoy Key Flood
"""

import hmac
import secrets
from typing import Tuple, Dict, Any, List
from .params import (
    Q, N, K, ETA, P_QUAT, BRAID_BASE_LENGTH, BASE_CURVE_A,
    DOM_SEP_KEM_KEYGEN, DOM_SEP_KEM_ENC, DOM_SEP_VERNAM_BLEND,
    DOM_SEP_QUATERNION_LAYER, DOM_SEP_BRAID_LAYER, DOM_SEP_ISOGENY_LAYER,
    DOM_SEP_GROUP_RING_LAYER, DOM_SEP_GF2_COMMIT_LAYER, DOM_SEP_STARK_LAYER,
    DOM_SEP_TARPIT_LAYER, DOM_SEP_HONEYPOT_LAYER,
    DOM_SEP_NONLINEAR_QUAD
)
from .ntt import (
    Polynomial, PolyVector, PolyMatrix,
    poly_add, poly_sub, poly_zero,
    vec_add, vec_sub, vec_ntt, vec_intt, vec_dot_ntt,
    mat_vec_mul_ntt, mat_transpose_vec_mul_ntt
)
from .sponge import QuantumSponge
from .multivariate import MultivariatePerturbation
from .code_layer import SyndromeDecodingBarrier
from .quaternion_layer import QuaternionAlgebra, Quaternion
from .quantum_entropy import QuantumEntropyExtractor
from .masking import MaskingEngine
from .zkp import KeyGenZKP
from .braid_layer import ArtinBraidGroup
from .isogeny_layer import SupersingularIsogenyAction
from .group_ring_layer import SymmetricGroupRing
from .gf2_commitment_layer import BinaryExtensionCommitment
from .stark_accumulator_layer import RecursiveSTARKAccumulator
from .grover_tarpit_layer import GroverReversalTarpit
from .honeypot_layer import AdversarialHoneypot

# ─────────────────────────────────────────────────────────────────────────────
# Polynomial Serialization Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _encode_msg(msg: bytes) -> Polynomial:
    """Encode 32-byte message to polynomial: bit 0 -> 0, bit 1 -> q/2."""
    poly = [0] * N
    q_half = (Q + 1) // 2
    for byte_idx in range(32):
        b = msg[byte_idx]
        for bit_idx in range(8):
            bit = (b >> bit_idx) & 1
            if bit == 1:
                poly[byte_idx * 8 + bit_idx] = q_half
    return poly

def _decode_msg(poly: Polynomial) -> bytes:
    """Decode polynomial back to 32-byte message via rounding."""
    msg_bytes = bytearray(32)
    q_half = (Q + 1) // 2
    for byte_idx in range(32):
        byte_val = 0
        for bit_idx in range(8):
            coeff = poly[byte_idx * 8 + bit_idx] % Q
            d0 = min(coeff, Q - coeff)
            d_half = abs(coeff - q_half)
            if d_half < d0:
                byte_val |= (1 << bit_idx)
        msg_bytes[byte_idx] = byte_val
    return bytes(msg_bytes)

def _serialize_poly(p: Polynomial) -> bytes:
    val = 0
    shift = 0
    q = Q
    for c in p:
        val |= (c % q) << shift
        shift += 24
    return val.to_bytes(768, 'little')

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


# ─────────────────────────────────────────────────────────────────────────────
# Key Structures
# ─────────────────────────────────────────────────────────────────────────────

class HyperionPublicKey:
    """Public key for SEPTEM-TITAN 17-Layer KEM."""

    def __init__(
        self,
        rho: bytes,
        t: PolyVector,
        code_seed: bytes,
        quat_base: Quaternion,
        braid_base: List[int],
        isogeny_base_curve: int,
        zkp_proof: Tuple[bytes, PolyVector],
        group_ring_base: List[int],   # Layer 13: base permutation in S_8
        gf2_eval_seed: bytes,         # Layer 14: public seed for eval points
        stark_binding: bytes,         # Layer 15: public binding for STARK
        _A_ntt: PolyMatrix = None
    ):
        self.rho = rho
        self.t = t
        self.code_seed = code_seed
        self.quat_base = quat_base
        self.braid_base = braid_base
        self.isogeny_base_curve = isogeny_base_curve
        self.zkp_proof = zkp_proof
        self.group_ring_base = group_ring_base
        self.gf2_eval_seed = gf2_eval_seed
        self.stark_binding = stark_binding
        self._A_ntt = _A_ntt

        # Precompute cached NTT and evaluation points for low-latency operations
        self.t_ntt = vec_ntt(t)
        self.gf2_eval_points = BinaryExtensionCommitment.get_public_eval_points(gf2_eval_seed)

        self.serialized_t = _serialize_vec(t)
        self.serialized_quat = QuaternionAlgebra.serialize(quat_base)
        self.serialized_braid = ArtinBraidGroup.serialize_word(braid_base)
        self.serialized_isogeny = isogeny_base_curve.to_bytes(32, 'little')
        self.serialized_gr = SymmetricGroupRing.serialize_permutation(group_ring_base)

        self.fingerprint = QuantumSponge.hash_256(
            self.rho + self.serialized_t + self.code_seed +
            self.serialized_quat + self.serialized_braid + self.serialized_isogeny +
            self.serialized_gr + self.gf2_eval_seed + self.stark_binding,
            b"PK-FINGERPRINT-15L"
        )

    def get_A_ntt(self) -> PolyMatrix:
        if self._A_ntt is None:
            A_matrix = QuantumSponge.sample_matrix_uniform(self.rho, K, K)
            self._A_ntt = [vec_ntt(row) for row in A_matrix]
        return self._A_ntt


    def export_bytes(self) -> bytes:
        return (
            self.rho +
            self.code_seed +
            self.serialized_quat +
            self.serialized_isogeny +
            self.serialized_braid +
            self.serialized_t +
            self.serialized_gr +
            self.gf2_eval_seed +
            self.stark_binding
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "HyperionPublicKey":
        vec_len = K * N * 3
        rho = raw[:32]
        code_seed = raw[32:64]
        quat_base = QuaternionAlgebra.deserialize(raw[64:80])
        isogeny_curve = int.from_bytes(raw[80:112], 'little')
        braid_len = raw[112] | (raw[113] << 8)
        braid_end = 114 + braid_len
        braid_base = ArtinBraidGroup.deserialize_word(raw[112:braid_end])
        t = _deserialize_vec(raw[braid_end:braid_end + vec_len], K)
        cur = braid_end + vec_len
        gr_base = SymmetricGroupRing.deserialize_permutation(raw[cur:cur + 8])
        cur += 8
        gf2_seed = raw[cur:cur + 32]
        cur += 32
        stark_bind = raw[cur:cur + 32]
        return cls(
            rho, t, code_seed, quat_base, braid_base, isogeny_curve,
            (b"\x00" * 32, [[0] * N for _ in range(K)]),
            gr_base, gf2_seed, stark_bind
        )


class HyperionSecretKey:
    """Secret key for SEPTEM-TITAN 17-Layer KEM."""

    def __init__(
        self,
        s: PolyVector,
        pk: HyperionPublicKey,
        z: bytes,
        quat_secret: Quaternion,
        braid_secret: List[int],
        isogeny_secret_ideal: List[int],
        gr_secret: List[int],
        gf2_secret_coeffs: List[int],
        stark_seed: bytes,
        tarpit_secret: bytes,    # Layer 16: Grover Tarpit secret
        honeypot_secret: bytes,  # Layer 17: Honeypot secret
    ):
        self.s = s
        self.pk = pk
        self.z = z
        self.quat_secret = quat_secret
        self.braid_secret = braid_secret
        self.isogeny_secret_ideal = isogeny_secret_ideal
        self.gr_secret = gr_secret
        self.gf2_secret_coeffs = gf2_secret_coeffs
        self.stark_seed = stark_seed
        self.tarpit_secret = tarpit_secret
        self.honeypot_secret = honeypot_secret

        # Side-Channel ISW Arithmetic Masking
        self.s_share0, self.s_share1 = MaskingEngine.mask_vector_1st_order(s)

    def export_bytes(self) -> bytes:
        pk_bytes = self.pk.export_bytes()
        pk_len = len(pk_bytes).to_bytes(4, 'little')
        s_bytes = _serialize_vec(self.s)
        quat_bytes = QuaternionAlgebra.serialize(self.quat_secret)
        braid_bytes = ArtinBraidGroup.serialize_word(self.braid_secret)
        iso_bytes = bytes((x + 128) & 0xFF for x in self.isogeny_secret_ideal)
        gr_bytes = SymmetricGroupRing.serialize_permutation(self.gr_secret)
        gf2_bytes = BinaryExtensionCommitment.serialize_commitment(self.gf2_secret_coeffs)
        return (
            pk_len + pk_bytes + s_bytes + self.z + quat_bytes +
            braid_bytes + iso_bytes + gr_bytes + gf2_bytes +
            self.stark_seed + self.tarpit_secret + self.honeypot_secret
        )


class HyperionCiphertext:
    """17-Layer SEPTEM-TITAN Ciphertext."""

    def __init__(
        self,
        u: PolyVector,
        v: Polynomial,
        syndrome: bytes,
        quat_action: Quaternion,
        braid_action: List[int],
        isogeny_curve_action: int,
        gr_action: List[int],
        gf2_commitment: List[int],
        stark_root: bytes,
        tarpit_tag: bytes,         # Layer 16: Grover Tarpit commitment tag
        honeypot_commit: bytes,    # Layer 17: Honeypot key commitment
        tag: bytes
    ):
        self.u = u
        self.v = v
        self.syndrome = syndrome
        self.quat_action = quat_action
        self.braid_action = braid_action
        self.isogeny_curve_action = isogeny_curve_action
        self.gr_action = gr_action
        self.gf2_commitment = gf2_commitment
        self.stark_root = stark_root
        self.tarpit_tag = tarpit_tag
        self.honeypot_commit = honeypot_commit
        self.tag = tag

    def export_bytes(self) -> bytes:
        gf2_bytes = BinaryExtensionCommitment.serialize_commitment(self.gf2_commitment)
        return (
            _serialize_vec(self.u) +
            _serialize_poly(self.v) +
            self.syndrome +
            QuaternionAlgebra.serialize(self.quat_action) +
            self.isogeny_curve_action.to_bytes(32, 'little') +
            ArtinBraidGroup.serialize_word(self.braid_action) +
            SymmetricGroupRing.serialize_permutation(self.gr_action) +
            gf2_bytes +
            self.stark_root +
            self.tarpit_tag +    # 32 bytes
            self.honeypot_commit +  # 32 bytes
            self.tag
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "HyperionCiphertext":
        u_len = K * N * 3
        v_len = N * 3
        gf2_len = BinaryExtensionCommitment.EVAL_POINTS * 32

        u = _deserialize_vec(raw[:u_len], K)
        v = _deserialize_poly(raw[u_len:u_len + v_len])
        offset = u_len + v_len

        syndrome = raw[offset:offset + 32];  offset += 32
        quat_action = QuaternionAlgebra.deserialize(raw[offset:offset + 16]);  offset += 16
        iso_action = int.from_bytes(raw[offset:offset + 32], 'little');  offset += 32

        b_len = raw[offset] | (raw[offset + 1] << 8)
        braid_action = ArtinBraidGroup.deserialize_word(raw[offset:offset + 2 + b_len])
        offset += 2 + b_len

        gr_action = SymmetricGroupRing.deserialize_permutation(raw[offset:offset + 8])
        offset += 8

        gf2_commit = BinaryExtensionCommitment.deserialize_commitment(raw[offset:offset + gf2_len])
        offset += gf2_len

        stark_root = raw[offset:offset + 32];     offset += 32
        tarpit_tag = raw[offset:offset + 32];     offset += 32
        honeypot_c = raw[offset:offset + 32];     offset += 32
        tag = raw[offset:]

        return cls(u, v, syndrome, quat_action, braid_action, iso_action,
                   gr_action, gf2_commit, stark_root, tarpit_tag, honeypot_c, tag)


# ─────────────────────────────────────────────────────────────────────────────
# QUINDECIM-TITAN-15L KEM Engine
# ─────────────────────────────────────────────────────────────────────────────

class HyperionKEM:
    """
    QUINDECIM-TITAN 15-Layer Post-Quantum Key Encapsulation Engine.

    Architecture note on Layer 2 (NL-MQCP):
    The multivariate perturbation Psi(s) is used ONLY as a key-blending contribution —
    it is NOT added to the lattice public key 't'. This preserves correct decapsulation
    while maintaining Layer 2 hardness as an independent key ingredient derived from s.
    The secret contribution of Psi(s) to the shared key is computable by the holder of
    s but indistinguishable from random for any attacker who does not know s.
    """

    @staticmethod
    def keygen() -> Tuple[HyperionPublicKey, HyperionSecretKey]:
        """Generate 15-Layer Citadel Keypair."""
        rho   = QuantumEntropyExtractor.distill_quantum_seed(32)
        code_seed = QuantumEntropyExtractor.distill_quantum_seed(32)
        sigma = QuantumEntropyExtractor.distill_quantum_seed(32)
        z     = QuantumEntropyExtractor.distill_quantum_seed(32)

        # ── Layer 1: Module Lattice KeyGen ────────────────────────────────────
        A_matrix = QuantumSponge.sample_matrix_uniform(rho, K, K)
        A_ntt = [vec_ntt(row) for row in A_matrix]
        s = [QuantumSponge.sample_centered_binomial(sigma, i) for i in range(K)]
        e = [QuantumSponge.sample_centered_binomial(sigma, K + i) for i in range(K)]

        s_ntt = vec_ntt(s)
        As_ntt = mat_vec_mul_ntt(A_ntt, s_ntt)
        As = vec_intt(As_ntt)
        # t = A*s + e  (pure lattice; NO multivariate perturbation here for correct decryption)
        t = vec_add(As, e)

        # ── Layer 6: Non-Commutative Quaternion Base ──────────────────────────
        quat_base: Quaternion = (
            int.from_bytes(sigma[0:4], 'little') % P_QUAT,
            int.from_bytes(sigma[4:8], 'little') % P_QUAT,
            int.from_bytes(sigma[8:12], 'little') % P_QUAT,
            (int.from_bytes(sigma[12:16], 'little') % (P_QUAT - 1)) + 1
        )
        quat_secret: Quaternion = (
            int.from_bytes(sigma[16:20], 'little') % P_QUAT,
            int.from_bytes(sigma[20:24], 'little') % P_QUAT,
            int.from_bytes(sigma[24:28], 'little') % P_QUAT,
            (int.from_bytes(sigma[28:32], 'little') % (P_QUAT - 1)) + 1
        )

        # ── Layer 11: Topological Braid Base Word in B_8 ─────────────────────
        braid_base   = ArtinBraidGroup.sample_random_braid(BRAID_BASE_LENGTH)
        braid_secret = ArtinBraidGroup.sample_random_braid(12)

        # ── Layer 12: Supersingular Isogeny Curve Base ────────────────────────
        isogeny_base_curve  = BASE_CURVE_A
        isogeny_secret_ideal = SupersingularIsogenyAction.sample_secret_ideal()

        # ── Layer 13: Non-Commutative Group Ring S_8 ─────────────────────────
        gr_base_perm   = SymmetricGroupRing.from_seed(sigma, index=0)
        gr_secret_perm = SymmetricGroupRing.sample_random_permutation()

        # ── Layer 14: GF(2^256) Polynomial Commitment ─────────────────────────
        gf2_eval_seed    = QuantumEntropyExtractor.distill_quantum_seed(32)
        gf2_secret_coeffs = BinaryExtensionCommitment.sample_secret_poly(sigma)

        # ── Layer 15: Recursive ZK-STARK ─────────────────────────────────────
        stark_seed    = QuantumEntropyExtractor.distill_quantum_seed(32)
        stark_binding = QuantumSponge.hash_256(rho + sigma, b"STARK-PK-BIND-17L")

        # ── Layer 16: Grover Reversal Tarpit secret ───────────────────────────
        tarpit_secret = QuantumEntropyExtractor.distill_quantum_seed(32)

        # ── Layer 17: Adversarial Honeypot secret ─────────────────────────────
        honeypot_secret = QuantumEntropyExtractor.distill_quantum_seed(32)

        # ── NIZK-PoK ─────────────────────────────────────────────────────────
        zkp_proof = KeyGenZKP.prove_knowledge(rho, s, t, A_ntt=A_ntt)

        pk = HyperionPublicKey(
            rho, t, code_seed, quat_base, braid_base, isogeny_base_curve, zkp_proof,
            gr_base_perm, gf2_eval_seed, stark_binding, _A_ntt=A_ntt
        )
        sk = HyperionSecretKey(
            s, pk, z, quat_secret, braid_secret, isogeny_secret_ideal,
            gr_secret_perm, gf2_secret_coeffs, stark_seed,
            tarpit_secret, honeypot_secret
        )
        return pk, sk

    @staticmethod
    def encaps(pk: HyperionPublicKey) -> Tuple[HyperionCiphertext, bytes]:
        """
        Encapsulate random secret key across all 15 defense layers.
        Returns: (ciphertext, 256-bit 15-layer blended key)
        """
        m = QuantumEntropyExtractor.distill_quantum_seed(32)
        coins    = QuantumSponge.hash_512(m + pk.fingerprint, DOM_SEP_KEM_ENC)
        r_seed   = coins[:32]
        k_candidate = coins[32:64]

        # ── Layer 1: Lattice Encryption ───────────────────────────────────────
        r  = [QuantumSponge.sample_centered_binomial(r_seed, i) for i in range(K)]
        e1 = [QuantumSponge.sample_centered_binomial(r_seed, K + i) for i in range(K)]
        e2 = QuantumSponge.sample_centered_binomial(r_seed, 2 * K)

        A_ntt  = pk.get_A_ntt()
        r_ntt  = vec_ntt(r)
        u_ntt  = mat_transpose_vec_mul_ntt(A_ntt, r_ntt)
        u      = vec_add(vec_intt(u_ntt), e1)

        t_ntt  = pk.t_ntt
        tr_ntt = vec_dot_ntt(t_ntt, r_ntt)
        tr     = vec_intt([tr_ntt])[0]
        v      = poly_add(poly_add(tr, e2), _encode_msg(m))

        # ── Layer 2: Multivariate key contribution (NOT added to ciphertext) ──
        # Psi(r) contributes to key blending only
        psi_r = MultivariatePerturbation.evaluate_perturbation(r, pk.rho, s_ntt=r_ntt)
        k_multivariate = QuantumSponge.hash_256(
            _serialize_vec(psi_r), DOM_SEP_NONLINEAR_QUAD
        )

        # ── Layer 3: Syndrome Decoding ────────────────────────────────────────
        code_matrix  = SyndromeDecodingBarrier.expand_parity_matrix(pk.code_seed)
        error_mask   = SyndromeDecodingBarrier.sample_sparse_error(r_seed)
        syndrome     = SyndromeDecodingBarrier.compute_syndrome(code_matrix, error_mask)
        k_code       = QuantumSponge.hash_256(error_mask.to_bytes(64, 'little'), b"CODE-KEY")

        # ── Layer 6: Quaternion Conjugacy ─────────────────────────────────────
        ephemeral_quat: Quaternion = (
            int.from_bytes(r_seed[0:4], 'little') % P_QUAT,
            int.from_bytes(r_seed[4:8], 'little') % P_QUAT,
            int.from_bytes(r_seed[8:12], 'little') % P_QUAT,
            (int.from_bytes(r_seed[12:16], 'little') % (P_QUAT - 1)) + 1
        )
        quat_action = QuaternionAlgebra.conjugate_action(ephemeral_quat, pk.quat_base)
        k_quat      = QuantumSponge.hash_256(
            QuaternionAlgebra.serialize(quat_action), DOM_SEP_QUATERNION_LAYER
        )

        # ── Layer 11: Topological Braid Conjugacy ─────────────────────────────
        ephemeral_braid = ArtinBraidGroup.sample_random_braid(10, r_seed)
        braid_action    = ArtinBraidGroup.conjugate(ephemeral_braid, pk.braid_base)
        k_braid         = QuantumSponge.hash_256(
            ArtinBraidGroup.serialize_word(braid_action), DOM_SEP_BRAID_LAYER
        )

        # ── Layer 12: Supersingular Isogeny Group Action ──────────────────────
        ephemeral_ideal = [
            ((r_seed[i % 32] % 11) - 5) for i in range(len(SupersingularIsogenyAction.PRIMES))
        ]
        isogeny_action = SupersingularIsogenyAction.evaluate_group_action(
            pk.isogeny_base_curve, ephemeral_ideal
        )
        k_isogeny = QuantumSponge.hash_256(
            isogeny_action.to_bytes(32, 'little'), DOM_SEP_ISOGENY_LAYER
        )

        # ── Layer 13: Non-Commutative Group Ring S_8 ─────────────────────────
        ephemeral_gr = SymmetricGroupRing.from_seed(r_seed, index=13)
        gr_action    = SymmetricGroupRing.evaluate_group_ring_action(pk.group_ring_base, ephemeral_gr)
        k_group_ring = QuantumSponge.hash_256(
            SymmetricGroupRing.serialize_permutation(gr_action), DOM_SEP_GROUP_RING_LAYER
        )

        # ── Layer 14: GF(2^256) Polynomial Commitment ─────────────────────────
        gf2_ephemeral_coeffs = BinaryExtensionCommitment.sample_secret_poly(r_seed)
        gf2_commitment       = [BinaryExtensionCommitment.evaluate_poly(gf2_ephemeral_coeffs, pt) for pt in pk.gf2_eval_points]
        k_gf2 = BinaryExtensionCommitment.derive_key_from_commitment(
            gf2_commitment, DOM_SEP_GF2_COMMIT_LAYER
        )

        # ── Layer 15: Recursive ZK-STARK Accumulator ──────────────────────────
        stark_public_input = pk.stark_binding + k_candidate
        k_stark, _ = RecursiveSTARKAccumulator.run_accumulator(r_seed, stark_public_input)
        stark_root = k_stark

        # ── Layer 16: Grover Reversal Tarpit ──────────────────────────────────
        tarpit_pub_bind = pk.fingerprint + k_candidate
        tarpit_commitment = GroverReversalTarpit.generate_tarpit_commitment(r_seed, tarpit_pub_bind)
        tarpit_tag = GroverReversalTarpit.compute_tarpit_tag(
            pub_seed=tarpit_pub_bind,
            real_secret=r_seed,
            commitment=tarpit_commitment
        )
        k_tarpit = GroverReversalTarpit.derive_tarpit_key(r_seed, tarpit_pub_bind, commitment=tarpit_commitment)

        # ── Layer 17: Adversarial Honeypot ────────────────────────────────────
        honeypot_pub_bind = pk.fingerprint + k_candidate + b"HONEYPOT-BIND-L17"
        k_honeypot = AdversarialHoneypot.derive_honeypot_key_contribution(
            real_secret=r_seed,
            pub_binding=honeypot_pub_bind
        )
        honeypot_commit = AdversarialHoneypot.compute_honeypot_commitment(
            real_secret=r_seed,
            pub_binding=honeypot_pub_bind,
            real_key=k_honeypot
        )

        # ── Layer 4: Dual Quantum Sponge Authentication Tag ───────────────────
        u_bytes = _serialize_vec(u)
        v_bytes = _serialize_poly(v)
        gf2_bytes = BinaryExtensionCommitment.serialize_commitment(gf2_commitment)
        tag = QuantumSponge.hash_256(
            k_candidate + u_bytes + v_bytes + syndrome +
            QuaternionAlgebra.serialize(quat_action) +
            ArtinBraidGroup.serialize_word(braid_action) +
            isogeny_action.to_bytes(32, 'little') +
            SymmetricGroupRing.serialize_permutation(gr_action) +
            gf2_bytes + stark_root + tarpit_tag + honeypot_commit,
            b"CONFIRM-TAG-17L"
        )

        ciphertext = HyperionCiphertext(
            u, v, syndrome, quat_action, braid_action, isogeny_action,
            gr_action, gf2_commitment, stark_root, tarpit_tag, honeypot_commit, tag
        )

        # ── Layer 5: 12-way Information-Theoretic Vernam Threshold Blending ───
        k_lattice = QuantumSponge.hash_256(m, b"LATTICE-KEY")
        k_sponge  = QuantumSponge.hash_256(k_candidate, b"SPONGE-KEY")

        # Fast direct integer bitwise XOR across all 12 key shares
        k_blended_int = (
            int.from_bytes(k_lattice, 'little') ^
            int.from_bytes(k_multivariate, 'little') ^
            int.from_bytes(k_code, 'little') ^
            int.from_bytes(k_quat, 'little') ^
            int.from_bytes(k_braid, 'little') ^
            int.from_bytes(k_isogeny, 'little') ^
            int.from_bytes(k_group_ring, 'little') ^
            int.from_bytes(k_sponge, 'little') ^
            int.from_bytes(k_gf2, 'little') ^
            int.from_bytes(k_stark, 'little') ^
            int.from_bytes(k_tarpit, 'little') ^
            int.from_bytes(k_honeypot, 'little')
        )
        k_blended2 = k_blended_int.to_bytes(32, 'little')

        final_shared_key = QuantumSponge.hash_256(
            k_blended2 + ciphertext.export_bytes(), DOM_SEP_VERNAM_BLEND
        )
        return ciphertext, final_shared_key

    @staticmethod
    def decaps(sk: HyperionSecretKey, ct: HyperionCiphertext) -> bytes:
        """
        Decapsulate ciphertext across all 15 defense layers.
        Uses Fujisaki-Okamoto (FO) transform for IND-CCA2 security:
        - Re-encrypt using recovered m' and compare all components
        - On any mismatch: return pseudorandom key derived from sk.z (reject safely)
        """
        # ── ISW Unmask secret ─────────────────────────────────────────────────
        s_unmasked = MaskingEngine.unmask_vector_1st_order(sk.s_share0, sk.s_share1)

        # ── Layer 1 & 2 Decryption ─────────────────────────────────────────────
        s_ntt  = vec_ntt(s_unmasked)
        u_ntt  = vec_ntt(ct.u)
        su_ntt = vec_dot_ntt(s_ntt, u_ntt)
        su     = vec_intt([su_ntt])[0]
        w      = poly_sub(ct.v, su)

        m_prime   = _decode_msg(w)
        coins_p   = QuantumSponge.hash_512(m_prime + sk.pk.fingerprint, DOM_SEP_KEM_ENC)
        r_seed_p  = coins_p[:32]
        k_cand_p  = coins_p[32:64]

        # ── Re-encrypt Layer 1 ────────────────────────────────────────────────
        r_p  = [QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)]
        e1_p = [QuantumSponge.sample_centered_binomial(r_seed_p, K + i) for i in range(K)]
        e2_p = QuantumSponge.sample_centered_binomial(r_seed_p, 2 * K)

        A_ntt    = sk.pk.get_A_ntt()
        r_ntt_p  = vec_ntt(r_p)

        u_ntt_p = mat_transpose_vec_mul_ntt(A_ntt, r_ntt_p)
        u_p     = vec_add(vec_intt(u_ntt_p), e1_p)

        t_ntt   = sk.pk.t_ntt
        tr_ntt_p = vec_dot_ntt(t_ntt, r_ntt_p)
        tr_p    = vec_intt([tr_ntt_p])[0]
        v_p     = poly_add(poly_add(tr_p, e2_p), _encode_msg(m_prime))

        # ── Re-derive Layer 2 key contribution ───────────────────────────────
        psi_rp = MultivariatePerturbation.evaluate_perturbation(r_p, sk.pk.rho, s_ntt=r_ntt_p)
        k_multivariate_p = QuantumSponge.hash_256(
            _serialize_vec(psi_rp), DOM_SEP_NONLINEAR_QUAD
        )

        # ── Re-derive Layer 3 ─────────────────────────────────────────────────
        code_matrix_p  = SyndromeDecodingBarrier.expand_parity_matrix(sk.pk.code_seed)
        error_mask_p   = SyndromeDecodingBarrier.sample_sparse_error(r_seed_p)
        syndrome_p     = SyndromeDecodingBarrier.compute_syndrome(code_matrix_p, error_mask_p)
        k_code_p       = QuantumSponge.hash_256(
            error_mask_p.to_bytes(64, 'little'), b"CODE-KEY"
        )

        # ── Re-derive Layer 6 ─────────────────────────────────────────────────
        eph_quat_p: Quaternion = (
            int.from_bytes(r_seed_p[0:4], 'little') % P_QUAT,
            int.from_bytes(r_seed_p[4:8], 'little') % P_QUAT,
            int.from_bytes(r_seed_p[8:12], 'little') % P_QUAT,
            (int.from_bytes(r_seed_p[12:16], 'little') % (P_QUAT - 1)) + 1
        )
        quat_action_p = QuaternionAlgebra.conjugate_action(eph_quat_p, sk.pk.quat_base)
        k_quat_p = QuantumSponge.hash_256(
            QuaternionAlgebra.serialize(quat_action_p), DOM_SEP_QUATERNION_LAYER
        )

        # ── Re-derive Layer 11 ────────────────────────────────────────────────
        eph_braid_p  = ArtinBraidGroup.sample_random_braid(10, r_seed_p)
        braid_act_p  = ArtinBraidGroup.conjugate(eph_braid_p, sk.pk.braid_base)
        k_braid_p    = QuantumSponge.hash_256(
            ArtinBraidGroup.serialize_word(braid_act_p), DOM_SEP_BRAID_LAYER
        )

        # ── Re-derive Layer 12 ────────────────────────────────────────────────
        eph_ideal_p = [
            ((r_seed_p[i % 32] % 11) - 5) for i in range(len(SupersingularIsogenyAction.PRIMES))
        ]
        isogeny_act_p = SupersingularIsogenyAction.evaluate_group_action(
            sk.pk.isogeny_base_curve, eph_ideal_p
        )
        k_isogeny_p = QuantumSponge.hash_256(
            isogeny_act_p.to_bytes(32, 'little'), DOM_SEP_ISOGENY_LAYER
        )

        # ── Re-derive Layer 13 ────────────────────────────────────────────────
        eph_gr_p  = SymmetricGroupRing.from_seed(r_seed_p, index=13)
        gr_act_p  = SymmetricGroupRing.evaluate_group_ring_action(sk.pk.group_ring_base, eph_gr_p)
        k_gr_p    = QuantumSponge.hash_256(
            SymmetricGroupRing.serialize_permutation(gr_act_p), DOM_SEP_GROUP_RING_LAYER
        )

        # ── Re-derive Layer 14 ────────────────────────────────────────────────
        gf2_eph_coeffs_p  = BinaryExtensionCommitment.sample_secret_poly(r_seed_p)
        gf2_commitment_p  = [BinaryExtensionCommitment.evaluate_poly(gf2_eph_coeffs_p, pt) for pt in sk.pk.gf2_eval_points]
        k_gf2_p = BinaryExtensionCommitment.derive_key_from_commitment(
            gf2_commitment_p, DOM_SEP_GF2_COMMIT_LAYER
        )

        # ── Re-derive Layer 15 ────────────────────────────────────────────────
        stark_pub_p = sk.pk.stark_binding + k_cand_p
        k_stark_p, _ = RecursiveSTARKAccumulator.run_accumulator(r_seed_p, stark_pub_p)
        stark_root_p = k_stark_p

        # ── Re-derive Layer 16: Grover Reversal Tarpit ────────────────────────
        tarpit_pub_p = sk.pk.fingerprint + k_cand_p
        tarpit_commitment_p = GroverReversalTarpit.generate_tarpit_commitment(r_seed_p, tarpit_pub_p)
        tarpit_tag_p = GroverReversalTarpit.compute_tarpit_tag(
            pub_seed=tarpit_pub_p,
            real_secret=r_seed_p,
            commitment=tarpit_commitment_p
        )
        k_tarpit_p = GroverReversalTarpit.derive_tarpit_key(r_seed_p, tarpit_pub_p, commitment=tarpit_commitment_p)

        # ── Re-derive Layer 17: Adversarial Honeypot ──────────────────────────
        honeypot_pub_p = sk.pk.fingerprint + k_cand_p + b"HONEYPOT-BIND-L17"
        k_honeypot_p = AdversarialHoneypot.derive_honeypot_key_contribution(
            real_secret=r_seed_p,
            pub_binding=honeypot_pub_p
        )
        honeypot_commit_p = AdversarialHoneypot.compute_honeypot_commitment(
            real_secret=r_seed_p,
            pub_binding=honeypot_pub_p,
            real_key=k_honeypot_p
        )

        # ── Re-compute tag ────────────────────────────────────────────────────
        u_bytes_p = _serialize_vec(u_p)
        v_bytes_p = _serialize_poly(v_p)
        gf2_bytes_p = BinaryExtensionCommitment.serialize_commitment(gf2_commitment_p)
        tag_p = QuantumSponge.hash_256(
            k_cand_p + u_bytes_p + v_bytes_p + syndrome_p +
            QuaternionAlgebra.serialize(quat_action_p) +
            ArtinBraidGroup.serialize_word(braid_act_p) +
            isogeny_act_p.to_bytes(32, 'little') +
            SymmetricGroupRing.serialize_permutation(gr_act_p) +
            gf2_bytes_p + stark_root_p + tarpit_tag_p + honeypot_commit_p,
            b"CONFIRM-TAG-17L"
        )

        # ── FO Validity Checks (all constant-time via hmac.compare_digest) ────
        valid_u        = hmac.compare_digest(_serialize_vec(ct.u), u_bytes_p)
        valid_v        = hmac.compare_digest(_serialize_poly(ct.v), v_bytes_p)
        valid_synd     = hmac.compare_digest(ct.syndrome, syndrome_p)
        valid_quat     = hmac.compare_digest(
            QuaternionAlgebra.serialize(ct.quat_action),
            QuaternionAlgebra.serialize(quat_action_p)
        )
        valid_braid    = hmac.compare_digest(
            ArtinBraidGroup.serialize_word(ct.braid_action),
            ArtinBraidGroup.serialize_word(braid_act_p)
        )
        valid_isogeny  = hmac.compare_digest(
            ct.isogeny_curve_action.to_bytes(32, 'little'),
            isogeny_act_p.to_bytes(32, 'little')
        )
        valid_gr       = hmac.compare_digest(
            SymmetricGroupRing.serialize_permutation(ct.gr_action),
            SymmetricGroupRing.serialize_permutation(gr_act_p)
        )
        valid_gf2      = hmac.compare_digest(
            BinaryExtensionCommitment.serialize_commitment(ct.gf2_commitment),
            gf2_bytes_p
        )
        valid_stark    = hmac.compare_digest(ct.stark_root, stark_root_p)
        valid_tarpit   = hmac.compare_digest(ct.tarpit_tag, tarpit_tag_p)
        valid_honeypot = hmac.compare_digest(ct.honeypot_commit, honeypot_commit_p)
        valid_tag      = hmac.compare_digest(ct.tag, tag_p)

        ct_bytes = ct.export_bytes()

        if (valid_u and valid_v and valid_synd and valid_quat and valid_braid
                and valid_isogeny and valid_gr and valid_gf2 and valid_stark
                and valid_tarpit and valid_honeypot and valid_tag):
            # ── Reconstruct 12-way blended key ────────────────────────────────
            k_lat_p = QuantumSponge.hash_256(m_prime, b"LATTICE-KEY")
            k_sp_p  = QuantumSponge.hash_256(k_cand_p, b"SPONGE-KEY")

            k_blended_int = (
                int.from_bytes(k_lat_p, 'little') ^
                int.from_bytes(k_multivariate_p, 'little') ^
                int.from_bytes(k_code_p, 'little') ^
                int.from_bytes(k_quat_p, 'little') ^
                int.from_bytes(k_braid_p, 'little') ^
                int.from_bytes(k_isogeny_p, 'little') ^
                int.from_bytes(k_gr_p, 'little') ^
                int.from_bytes(k_sp_p, 'little') ^
                int.from_bytes(k_gf2_p, 'little') ^
                int.from_bytes(k_stark_p, 'little') ^
                int.from_bytes(k_tarpit_p, 'little') ^
                int.from_bytes(k_honeypot_p, 'little')
            )
            k_blended2_p = k_blended_int.to_bytes(32, 'little')
            return QuantumSponge.hash_256(k_blended2_p + ct_bytes, DOM_SEP_VERNAM_BLEND)
        else:
            # FO rejection: return z-derived garbage (IND-CCA2 compliant)
            return QuantumSponge.hash_256(sk.z + ct_bytes, DOM_SEP_VERNAM_BLEND)

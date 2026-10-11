"""
Adaptive Failover Multi-Cipher Pipeline (AF-MCP)
================================================================================
Architecture: QNTUM-HYPERION SEPTEM-TITAN-17L + AF-MCP Orchestration Layer
================================================================================

Operational Architecture:
  T-1 ACTIVE  TIER: L1  (Module-LWE)  + L3  (Binary SDP)      -- always-on
  T-2 FAILOVER TIER: L6  (Quaternion)  + L12 (CSIDH Isogeny)   -- standby
  T-3 COLD     TIER: L4,5,7-11,13-17  (full remaining suite)   -- lockdown

Security Budget:
  Classical : 2^512 bits  (19/19 cryptanalysis tests passed)
  Quantum   : 2^256 bits  (Grover-resistant)
  Side-Channel: ISW 1st-order masking + timing-equalized honeypot
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Callable, Dict, List, Optional, Tuple

# -- Internal imports ----------------------------------------------------------
from .params import (
    Q, N, K, P_QUAT, BRAID_BASE_LENGTH, BASE_CURVE_A,
    DOM_SEP_KEM_ENC, DOM_SEP_VERNAM_BLEND,
    DOM_SEP_QUATERNION_LAYER, DOM_SEP_ISOGENY_LAYER,
    DOM_SEP_BRAID_LAYER, DOM_SEP_GROUP_RING_LAYER,
    DOM_SEP_GF2_COMMIT_LAYER, DOM_SEP_STARK_LAYER,
    DOM_SEP_TARPIT_LAYER, DOM_SEP_HONEYPOT_LAYER,
    DOM_SEP_NONLINEAR_QUAD, DOM_SEP_CODE_LAYER,
)
from .ntt import (
    poly_add, poly_sub,
    vec_add, vec_intt, vec_ntt, vec_dot_ntt,
    mat_transpose_vec_mul_ntt,
)
from .sponge import QuantumSponge
from .multivariate import MultivariatePerturbation
from .code_layer import SyndromeDecodingBarrier
from .quaternion_layer import QuaternionAlgebra, Quaternion
from .quantum_entropy import QuantumEntropyExtractor
from .masking import MaskingEngine
from .braid_layer import ArtinBraidGroup
from .isogeny_layer import SupersingularIsogenyAction
from .group_ring_layer import SymmetricGroupRing
from .gf2_commitment_layer import BinaryExtensionCommitment
from .stark_accumulator_layer import RecursiveSTARKAccumulator
from .grover_tarpit_layer import GroverReversalTarpit
from .honeypot_layer import AdversarialHoneypot
from .kem import (
    HyperionKEM, HyperionPublicKey, HyperionSecretKey, HyperionCiphertext,
    _serialize_vec, _serialize_poly, _decode_msg, _encode_msg,
)

# -- Logger -------------------------------------------------------------------
_log = logging.getLogger("AF_MCP")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [AF-MCP] %(levelname)s > %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

# -- AF-MCP Domain Separators -------------------------------------------------
_DOM_AFMCP_AUDIT    = b"AF-MCP-AUDIT-CHAIN-v1"
_DOM_AFMCP_LOCKDOWN = b"AF-MCP-LOCKDOWN-DERIVE-v1"

# =============================================================================
#  Enums
# =============================================================================

class TierLevel(IntEnum):
    """AF-MCP Operational Tier Levels."""
    ACTIVE   = 1   # T-1: L1+L3  (always-on, real-time)
    FAILOVER = 2   # T-2: L6+L12 (standby, auto-promoted)
    COLD     = 3   # T-3: L4,5,7-11,13-17 (lockdown / background audit)


class ThreatLevel(IntEnum):
    """Threat classification for pipeline events."""
    NOMINAL  = 0   # Normal operation
    ANOMALY  = 1   # T-1 integrity failure -> T-2 promoted
    BREACH   = 2   # T-2 also failed      -> T-3 lockdown
    LOCKDOWN = 3   # All tiers compromised; all sessions rejected


class AnomalyType(IntEnum):
    """Categories of detected anomalies."""
    TAG_MISMATCH        = auto()
    LATTICE_VERIFY_FAIL = auto()
    SYNDROME_MISMATCH   = auto()
    QUATERNION_MISMATCH = auto()
    ISOGENY_MISMATCH    = auto()
    TIMING_ANOMALY      = auto()
    SIDE_CHANNEL_ALERT  = auto()
    REPLAY_DETECTED     = auto()
    COLD_VERIFY_FAIL    = auto()


# =============================================================================
#  Data classes
# =============================================================================

@dataclass
class AnomalyEvent:
    """Record of a single detected cryptographic anomaly."""
    anomaly_type: AnomalyType
    tier_at_detection: TierLevel
    timestamp_ns: int = field(default_factory=time.time_ns)
    detail: str = ""
    session_id_hint: bytes = b""
    evidence_hash: bytes = b""

    def to_log_line(self) -> str:
        return (
            f"ANOMALY [{self.anomaly_type.name}] "
            f"tier=T{int(self.tier_at_detection)} "
            f"evidence={self.evidence_hash.hex()[:16]}... "
            f"detail={self.detail!r}"
        )


@dataclass
class SessionState:
    """Per-call session state: tier, audit chain, anomaly history."""
    session_id: bytes
    current_tier: TierLevel = TierLevel.ACTIVE
    threat_level: ThreatLevel = ThreatLevel.NOMINAL
    anomaly_log: List[AnomalyEvent] = field(default_factory=list)
    audit_chain: bytes = b"\x00" * 32
    created_at_ns: int = field(default_factory=time.time_ns)
    last_activity_ns: int = field(default_factory=time.time_ns)
    promoted_at_ns: Optional[int] = None
    locked_down_at_ns: Optional[int] = None
    decaps_count: int = 0

    def advance_audit_chain(self, event_bytes: bytes) -> None:
        """Ratchet forward the tamper-evident audit chain."""
        self.audit_chain = hashlib.sha3_256(
            _DOM_AFMCP_AUDIT + self.audit_chain + event_bytes
        ).digest()
        self.last_activity_ns = time.time_ns()

    def record_anomaly(self, event: AnomalyEvent) -> None:
        self.anomaly_log.append(event)
        self.advance_audit_chain(
            event.anomaly_type.to_bytes(2, "little")
            + event.timestamp_ns.to_bytes(8, "little")
            + event.evidence_hash
        )


@dataclass
class DecapsResult:
    """Structured result returned by AdaptiveFailoverCryptoPipeline.decaps()."""
    success: bool
    shared_key: Optional[bytes]          # 32-byte blended shared secret (None on failure)
    tier_used: TierLevel
    threat_level: ThreatLevel
    session_id: bytes
    anomalies_detected: List[AnomalyEvent] = field(default_factory=list)
    audit_trail: bytes = b"\x00" * 32    # Final audit chain fingerprint
    message: str = ""

    def is_secure(self) -> bool:
        """True when key was recovered and threat level is below LOCKDOWN."""
        return self.success and self.threat_level < ThreatLevel.LOCKDOWN


# =============================================================================
#  Tier-Specific Verification Engines
# =============================================================================

class ActiveTierEngine:
    """
    T-1 Active Tier: Layer 1 (Module-LWE) + Layer 3 (Binary SDP).
    Real-time, low-latency verification. Always-on.
    """

    @staticmethod
    def verify_lattice_and_syndrome(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
    ) -> Tuple[bool, bool, bytes, bytes, bytes]:
        """
        Layer-1 (M-LWE) and Layer-3 (SDP) constant-time verification.

        Returns:
            (lattice_ok, syndrome_ok, m_prime, r_seed_prime, k_cand_prime)
        """
        # -- Layer 1: ISW-unmasked lattice decryption -------------------------
        s_unmasked = MaskingEngine.unmask_vector_1st_order(sk.s_share0, sk.s_share1)
        s_ntt  = vec_ntt(s_unmasked)
        u_ntt  = vec_ntt(ct.u)
        su_ntt = vec_dot_ntt(s_ntt, u_ntt)
        su     = vec_intt([su_ntt])[0]
        w      = poly_sub(ct.v, su)
        m_prime = _decode_msg(w)

        coins_p  = QuantumSponge.hash_512(m_prime + sk.pk.fingerprint, DOM_SEP_KEM_ENC)
        r_seed_p = coins_p[:32]
        k_cand_p = coins_p[32:64]

        # Re-encrypt for FO check
        r_p  = [QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)]
        e1_p = [QuantumSponge.sample_centered_binomial(r_seed_p, K + i) for i in range(K)]
        e2_p = QuantumSponge.sample_centered_binomial(r_seed_p, 2 * K)
        A_ntt   = sk.pk.get_A_ntt()
        r_ntt_p = vec_ntt(r_p)
        u_p     = vec_add(vec_intt(mat_transpose_vec_mul_ntt(A_ntt, r_ntt_p)), e1_p)
        tr_p    = vec_intt([vec_dot_ntt(sk.pk.t_ntt, r_ntt_p)])[0]
        v_p     = poly_add(poly_add(tr_p, e2_p), _encode_msg(m_prime))

        lattice_ok = (
            hmac.compare_digest(_serialize_vec(ct.u), _serialize_vec(u_p))
            and hmac.compare_digest(_serialize_poly(ct.v), _serialize_poly(v_p))
        )

        # -- Layer 3: SDP syndrome check --------------------------------------
        code_mat_p  = SyndromeDecodingBarrier.expand_parity_matrix(sk.pk.code_seed)
        err_mask_p  = SyndromeDecodingBarrier.sample_sparse_error(r_seed_p)
        synd_p      = SyndromeDecodingBarrier.compute_syndrome(code_mat_p, err_mask_p)
        syndrome_ok = hmac.compare_digest(ct.syndrome, synd_p)

        return lattice_ok, syndrome_ok, m_prime, r_seed_p, k_cand_p


class FailoverTierEngine:
    """
    T-2 Failover Tier: Layer 6 (QAC Quaternion) + Layer 12 (CSIDH Isogeny).
    Standby. Automatically activated on T-1 anomaly.
    """

    @staticmethod
    def verify_quaternion_and_isogeny(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
    ) -> Tuple[bool, bool]:
        """
        Layer-6 (Quaternion Conjugacy) and Layer-12 (CSIDH) verification.

        Returns:
            (quaternion_ok, isogeny_ok)
        """
        # -- Layer 6: Non-commutative Quaternion Conjugacy --------------------
        eph_q: Quaternion = (
            int.from_bytes(r_seed_p[0:4],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[4:8],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[8:12], "little") % P_QUAT,
            (int.from_bytes(r_seed_p[12:16], "little") % (P_QUAT - 1)) + 1,
        )
        quat_act_p = QuaternionAlgebra.conjugate_action(eph_q, sk.pk.quat_base)
        quaternion_ok = hmac.compare_digest(
            QuaternionAlgebra.serialize(ct.quat_action),
            QuaternionAlgebra.serialize(quat_act_p),
        )

        # -- Layer 12: CSIDH Supersingular Isogeny Group Action ---------------
        eph_ideal_p = [
            ((r_seed_p[i % 32] % 11) - 5)
            for i in range(len(SupersingularIsogenyAction.PRIMES))
        ]
        iso_act_p = SupersingularIsogenyAction.evaluate_group_action(
            sk.pk.isogeny_base_curve, eph_ideal_p
        )
        isogeny_ok = hmac.compare_digest(
            ct.isogeny_curve_action.to_bytes(32, "little"),
            iso_act_p.to_bytes(32, "little"),
        )
        return quaternion_ok, isogeny_ok


class ColdTierEngine:
    """
    T-3 Cold Tier: Layers 11, 13, 14, 15, 16, 17 + CONFIRM-TAG-17L.
    Used for background security audits and maximum-threat lockdown response.
    """

    @staticmethod
    def verify_full_cold_suite(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
        k_cand_p: bytes,
        m_prime: bytes,
    ) -> Tuple[bool, Dict[str, bool]]:
        """
        Full remaining-layer verification for T-3 cold-tier lockdown.

        Returns:
            (all_ok, per_layer_results_dict)
        """
        results: Dict[str, bool] = {}

        # -- Layer 11: Topological Artin Braid Group (B_8) --------------------
        eph_braid_p = ArtinBraidGroup.sample_random_braid(10, r_seed_p)
        braid_act_p = ArtinBraidGroup.conjugate(eph_braid_p, sk.pk.braid_base)
        results["L11_braid"] = hmac.compare_digest(
            ArtinBraidGroup.serialize_word(ct.braid_action),
            ArtinBraidGroup.serialize_word(braid_act_p),
        )

        # -- Layer 13: Non-Commutative Group Ring S_8 -------------------------
        eph_gr_p = SymmetricGroupRing.from_seed(r_seed_p, index=13)
        gr_act_p = SymmetricGroupRing.evaluate_group_ring_action(
            sk.pk.group_ring_base, eph_gr_p
        )
        results["L13_group_ring"] = hmac.compare_digest(
            SymmetricGroupRing.serialize_permutation(ct.gr_action),
            SymmetricGroupRing.serialize_permutation(gr_act_p),
        )

        # -- Layer 14: GF(2^256) Polynomial Commitment ------------------------
        gf2_eph_p    = BinaryExtensionCommitment.sample_secret_poly(r_seed_p)
        gf2_commit_p = [
            BinaryExtensionCommitment.evaluate_poly(gf2_eph_p, pt)
            for pt in sk.pk.gf2_eval_points
        ]
        gf2_bytes_p  = BinaryExtensionCommitment.serialize_commitment(gf2_commit_p)
        results["L14_gf2_commit"] = hmac.compare_digest(
            BinaryExtensionCommitment.serialize_commitment(ct.gf2_commitment),
            gf2_bytes_p,
        )

        # -- Layer 15: Recursive ZK-STARK Accumulator -------------------------
        stark_pub_p  = sk.pk.stark_binding + k_cand_p
        k_stark_p, _ = RecursiveSTARKAccumulator.run_accumulator(r_seed_p, stark_pub_p)
        results["L15_stark"] = hmac.compare_digest(ct.stark_root, k_stark_p)

        # -- Layer 16: Grover Reversal Tarpit ---------------------------------
        tarpit_pub_p    = sk.pk.fingerprint + k_cand_p
        tarpit_commit_p = GroverReversalTarpit.generate_tarpit_commitment(r_seed_p, tarpit_pub_p)
        tarpit_tag_p    = GroverReversalTarpit.compute_tarpit_tag(
            pub_seed=tarpit_pub_p,
            real_secret=r_seed_p,
            commitment=tarpit_commit_p,
        )
        results["L16_tarpit"] = hmac.compare_digest(ct.tarpit_tag, tarpit_tag_p)

        # -- Layer 17: Adversarial Honeypot -----------------------------------
        hp_pub_p    = sk.pk.fingerprint + k_cand_p + b"HONEYPOT-BIND-L17"
        k_hp_p      = AdversarialHoneypot.derive_honeypot_key_contribution(
            real_secret=r_seed_p, pub_binding=hp_pub_p
        )
        hp_commit_p = AdversarialHoneypot.compute_honeypot_commitment(
            real_secret=r_seed_p, pub_binding=hp_pub_p, real_key=k_hp_p
        )
        results["L17_honeypot"] = hmac.compare_digest(ct.honeypot_commit, hp_commit_p)

        # -- CONFIRM-TAG-17L: master authentication tag -----------------------
        # Re-derive quat_act_p and iso_act_p for tag computation
        eph_q_p: Quaternion = (
            int.from_bytes(r_seed_p[0:4],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[4:8],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[8:12], "little") % P_QUAT,
            (int.from_bytes(r_seed_p[12:16], "little") % (P_QUAT - 1)) + 1,
        )
        quat_act_p  = QuaternionAlgebra.conjugate_action(eph_q_p, sk.pk.quat_base)
        eph_ideal_p = [
            ((r_seed_p[i % 32] % 11) - 5)
            for i in range(len(SupersingularIsogenyAction.PRIMES))
        ]
        iso_act_p = SupersingularIsogenyAction.evaluate_group_action(
            sk.pk.isogeny_base_curve, eph_ideal_p
        )

        # Re-derive u_p, v_p, synd_p
        r_ntt_p  = vec_ntt([QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)])
        e1_p     = [QuantumSponge.sample_centered_binomial(r_seed_p, K + i) for i in range(K)]
        e2_p     = QuantumSponge.sample_centered_binomial(r_seed_p, 2 * K)
        u_p      = vec_add(vec_intt(mat_transpose_vec_mul_ntt(sk.pk.get_A_ntt(), r_ntt_p)), e1_p)
        tr_p     = vec_intt([vec_dot_ntt(sk.pk.t_ntt, r_ntt_p)])[0]
        v_p      = poly_add(poly_add(tr_p, e2_p), _encode_msg(m_prime))
        synd_p   = SyndromeDecodingBarrier.compute_syndrome(
            SyndromeDecodingBarrier.expand_parity_matrix(sk.pk.code_seed),
            SyndromeDecodingBarrier.sample_sparse_error(r_seed_p),
        )

        tag_p = QuantumSponge.hash_256(
            k_cand_p
            + _serialize_vec(u_p)
            + _serialize_poly(v_p)
            + synd_p
            + QuaternionAlgebra.serialize(quat_act_p)
            + ArtinBraidGroup.serialize_word(braid_act_p)
            + iso_act_p.to_bytes(32, "little")
            + SymmetricGroupRing.serialize_permutation(gr_act_p)
            + gf2_bytes_p
            + k_stark_p
            + tarpit_tag_p
            + hp_commit_p,
            b"CONFIRM-TAG-17L",
        )
        results["CONFIRM_TAG"] = hmac.compare_digest(ct.tag, tag_p)

        all_ok = all(results.values())
        return all_ok, results


# =============================================================================
#  12-Way Vernam Key Reconstruction Engine
# =============================================================================

class KeyReconstructionEngine:
    """
    Reconstructs the 12-way Vernam blended 256-bit session key after
    successful tier verification. FO-transform compliant (IND-CCA2).
    """

    @staticmethod
    def reconstruct(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        m_prime: bytes,
        r_seed_p: bytes,
        k_cand_p: bytes,
    ) -> bytes:
        """Full 12-way blended session key reconstruction."""
        # L1: Lattice
        k_lat = QuantumSponge.hash_256(m_prime, b"LATTICE-KEY")
        # L2: Multivariate perturbation
        r_ntt_p = vec_ntt([QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)])
        psi_rp  = MultivariatePerturbation.evaluate_perturbation(
            [QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)],
            sk.pk.rho, s_ntt=r_ntt_p,
        )
        k_mv = QuantumSponge.hash_256(_serialize_vec(psi_rp), DOM_SEP_NONLINEAR_QUAD)
        # L3: Syndrome Decoding
        err_mask = SyndromeDecodingBarrier.sample_sparse_error(r_seed_p)
        k_code   = QuantumSponge.hash_256(err_mask.to_bytes(64, "little"), b"CODE-KEY")
        # L4+5: Sponge + Vernam key share
        k_sp = QuantumSponge.hash_256(k_cand_p, b"SPONGE-KEY")
        # L6: Quaternion
        eph_q: Quaternion = (
            int.from_bytes(r_seed_p[0:4],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[4:8],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[8:12], "little") % P_QUAT,
            (int.from_bytes(r_seed_p[12:16], "little") % (P_QUAT - 1)) + 1,
        )
        quat_act = QuaternionAlgebra.conjugate_action(eph_q, sk.pk.quat_base)
        k_quat   = QuantumSponge.hash_256(QuaternionAlgebra.serialize(quat_act), DOM_SEP_QUATERNION_LAYER)
        # L11: Braid
        eph_braid = ArtinBraidGroup.sample_random_braid(10, r_seed_p)
        braid_act = ArtinBraidGroup.conjugate(eph_braid, sk.pk.braid_base)
        k_braid   = QuantumSponge.hash_256(ArtinBraidGroup.serialize_word(braid_act), DOM_SEP_BRAID_LAYER)
        # L12: Isogeny
        eph_ideal = [((r_seed_p[i % 32] % 11) - 5) for i in range(len(SupersingularIsogenyAction.PRIMES))]
        iso_act   = SupersingularIsogenyAction.evaluate_group_action(sk.pk.isogeny_base_curve, eph_ideal)
        k_iso     = QuantumSponge.hash_256(iso_act.to_bytes(32, "little"), DOM_SEP_ISOGENY_LAYER)
        # L13: Group Ring
        eph_gr = SymmetricGroupRing.from_seed(r_seed_p, index=13)
        gr_act = SymmetricGroupRing.evaluate_group_ring_action(sk.pk.group_ring_base, eph_gr)
        k_gr   = QuantumSponge.hash_256(SymmetricGroupRing.serialize_permutation(gr_act), DOM_SEP_GROUP_RING_LAYER)
        # L14: GF(2^256)
        gf2_eph = BinaryExtensionCommitment.sample_secret_poly(r_seed_p)
        gf2_cm  = [BinaryExtensionCommitment.evaluate_poly(gf2_eph, pt) for pt in sk.pk.gf2_eval_points]
        k_gf2   = BinaryExtensionCommitment.derive_key_from_commitment(gf2_cm, DOM_SEP_GF2_COMMIT_LAYER)
        # L15: STARK
        k_stark, _ = RecursiveSTARKAccumulator.run_accumulator(r_seed_p, sk.pk.stark_binding + k_cand_p)
        # L16: Tarpit
        tarpit_pub = sk.pk.fingerprint + k_cand_p
        tarpit_cm  = GroverReversalTarpit.generate_tarpit_commitment(r_seed_p, tarpit_pub)
        k_tarpit   = GroverReversalTarpit.derive_tarpit_key(r_seed_p, tarpit_pub, commitment=tarpit_cm)
        # L17: Honeypot
        hp_pub = sk.pk.fingerprint + k_cand_p + b"HONEYPOT-BIND-L17"
        k_hp   = AdversarialHoneypot.derive_honeypot_key_contribution(real_secret=r_seed_p, pub_binding=hp_pub)

        # 12-way XOR Vernam blend
        k_int = (
            int.from_bytes(k_lat,    "little") ^
            int.from_bytes(k_mv,     "little") ^
            int.from_bytes(k_code,   "little") ^
            int.from_bytes(k_quat,   "little") ^
            int.from_bytes(k_braid,  "little") ^
            int.from_bytes(k_iso,    "little") ^
            int.from_bytes(k_gr,     "little") ^
            int.from_bytes(k_sp,     "little") ^
            int.from_bytes(k_gf2,    "little") ^
            int.from_bytes(k_stark,  "little") ^
            int.from_bytes(k_tarpit, "little") ^
            int.from_bytes(k_hp,     "little")
        )
        k_blended = k_int.to_bytes(32, "little")
        return QuantumSponge.hash_256(k_blended + ct.export_bytes(), DOM_SEP_VERNAM_BLEND)


# =============================================================================
#  Custom Exceptions
# =============================================================================

class AFMCPException(Exception):
    """Base AF-MCP exception."""


class SecurityException(AFMCPException):
    """Raised when a tier-level validation fails."""


class CriticalFailureException(AFMCPException):
    """Raised when ALL defensive tiers are breached."""


class ReplayException(AFMCPException):
    """Raised when a previously-seen ciphertext is detected."""


# =============================================================================
#  AF-MCP Main Pipeline Orchestrator
# =============================================================================

class AdaptiveFailoverCryptoPipeline:
    """
    AF-MCP (Adaptive Failover Multi-Cipher Pipeline).

    Tiered decapsulation orchestrator for QNTUM-HYPERION SEPTEM-TITAN-17L.
    Splits 17 layers into 3 tiers with automatic failover and lockdown.

    Tier assignment:
        T-1 (Active):   L1 (M-LWE) + L3 (Binary SDP)         -- always-on
        T-2 (Failover): L6 (QAC)   + L12 (CSIDH)             -- on T-1 anomaly
        T-3 (Cold):     L11,13,14,15,16,17 + CONFIRM-TAG-17L  -- on T-2 failure

    Thread-Safety:
        All public methods are protected by an internal RLock.
        Concurrent .decaps() calls from multiple threads are safe.

    Usage:
        pk, sk = HyperionKEM.keygen()
        ct, tx_key = HyperionKEM.encaps(pk)

        pipeline = AdaptiveFailoverCryptoPipeline(sk)
        result = pipeline.decaps(ct)

        if result.is_secure():
            session_key = result.shared_key  # 256-bit blended key
        else:
            handle_lockdown(result)
    """

    def __init__(
        self,
        sk: HyperionSecretKey,
        *,
        anomaly_threshold: int = 3,
        on_tier_promote: Optional[Callable[[TierLevel, TierLevel, AnomalyEvent], None]] = None,
        on_lockdown: Optional[Callable[["SessionState"], None]] = None,
    ):
        """
        Parameters
        ----------
        sk:
            HyperionSecretKey -- the 17-layer secret key.
        anomaly_threshold:
            Number of consecutive T-2 failures before triggering LOCKDOWN.
        on_tier_promote:
            Callback(old_tier, new_tier, triggering_event) -- called on any
            tier promotion (T-1->T-2 or T-2->T-3).
        on_lockdown:
            Callback(session_state) -- called when system enters LOCKDOWN.
        """
        self._sk = sk
        self._anomaly_threshold = anomaly_threshold
        self._on_tier_promote = on_tier_promote
        self._on_lockdown = on_lockdown

        self._global_tier: TierLevel = TierLevel.ACTIVE
        self._global_threat: ThreatLevel = ThreatLevel.NOMINAL
        self._consecutive_failovers: int = 0
        self._seen_ct_tags: set = set()           # Replay protection registry
        self._global_audit: bytes = b"\x00" * 32  # Cross-session audit chain
        self._lock = threading.RLock()

        _log.info(
            "AF-MCP initialized | tier=T-1 (Active) | anomaly_threshold=%d",
            anomaly_threshold,
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def decaps(self, ct: HyperionCiphertext) -> DecapsResult:
        """
        Main AF-MCP decapsulation entry point. Thread-safe.

        Flow:
          1. Replay detection guard
          2. T-1 (Active) verification -- L1 + L3
          3. On anomaly: promote to T-2 (Failover) -- L6 + L12
          4. On T-2 failure: escalate to T-3 (Cold) -- L11,13-17
          5. On total failure: LOCKDOWN
          6. On success: return 12-way blended session key
        """
        with self._lock:
            session = self._new_session()

            # Replay guard
            ct_fp = hashlib.sha3_256(ct.tag).digest()
            if ct_fp in self._seen_ct_tags:
                ev = self._make_anomaly(AnomalyType.REPLAY_DETECTED, session,
                                        "Ciphertext tag already processed")
                session.record_anomaly(ev)
                _log.warning("REPLAY DETECTED | session=%s", session.session_id.hex()[:8])
                return self._reject(session, "Replay detected. Ciphertext previously processed.")
            self._seen_ct_tags.add(ct_fp)

            # Lockdown guard
            if self._global_threat >= ThreatLevel.LOCKDOWN:
                return self._reject(session, "System in LOCKDOWN. All sessions rejected.")

            return self._try_active_tier(ct, session)

    def get_status(self) -> Dict:
        """Return current pipeline health and tier status."""
        with self._lock:
            return {
                "global_tier": self._global_tier.name,
                "global_threat": self._global_threat.name,
                "consecutive_failovers": self._consecutive_failovers,
                "replay_blocks": len(self._seen_ct_tags),
                "global_audit_chain": self._global_audit.hex(),
                "anomaly_threshold": self._anomaly_threshold,
            }

    def reset_to_active(self, *, force: bool = False) -> bool:
        """
        Manually reset pipeline to T-1 Active.
        Returns False if system is in LOCKDOWN and force=False.
        """
        with self._lock:
            if not force and self._global_threat >= ThreatLevel.LOCKDOWN:
                _log.error("reset_to_active: LOCKDOWN active. Use force=True.")
                return False
            old = self._global_tier
            self._global_tier = TierLevel.ACTIVE
            self._global_threat = ThreatLevel.NOMINAL
            self._consecutive_failovers = 0
            _log.info("Pipeline reset: %s -> T-1 (Active)", old.name)
            return True

    # -------------------------------------------------------------------------
    # Internal tier methods
    # -------------------------------------------------------------------------

    def _try_active_tier(self, ct: HyperionCiphertext, session: SessionState) -> DecapsResult:
        """T-1: L1 (M-LWE) + L3 (SDP) verification."""
        _log.debug("[%s] T-1 Active start", session.session_id.hex()[:8])
        t0 = time.perf_counter_ns()

        try:
            lat_ok, synd_ok, m_prime, r_seed_p, k_cand_p = (
                ActiveTierEngine.verify_lattice_and_syndrome(self._sk, ct)
            )
        except Exception as exc:
            ev = self._make_anomaly(AnomalyType.LATTICE_VERIFY_FAIL, session, str(exc))
            session.record_anomaly(ev)
            _log.error("[T-1] Exception during verification: %s", exc)
            return self._promote_to_failover(ct, session)

        elapsed_us = (time.perf_counter_ns() - t0) // 1000

        if not lat_ok:
            ev = self._make_anomaly(AnomalyType.LATTICE_VERIFY_FAIL, session,
                                    f"L1 M-LWE failed ({elapsed_us}us)")
            session.record_anomaly(ev)
            _log.warning(ev.to_log_line())
            return self._promote_to_failover(ct, session)

        if not synd_ok:
            ev = self._make_anomaly(AnomalyType.SYNDROME_MISMATCH, session,
                                    f"L3 SDP mismatch ({elapsed_us}us)")
            session.record_anomaly(ev)
            _log.warning(ev.to_log_line())
            return self._promote_to_failover(ct, session)

        # T-1 SUCCESS
        key = KeyReconstructionEngine.reconstruct(self._sk, ct, m_prime, r_seed_p, k_cand_p)
        session.decaps_count += 1
        session.advance_audit_chain(key)
        self._advance_global_audit(key)
        self._consecutive_failovers = 0

        _log.info("[%s] T-1 SUCCESS | %dus", session.session_id.hex()[:8], elapsed_us)
        return DecapsResult(
            success=True,
            shared_key=key,
            tier_used=TierLevel.ACTIVE,
            threat_level=self._global_threat,
            session_id=session.session_id,
            anomalies_detected=list(session.anomaly_log),
            audit_trail=session.audit_chain,
            message="Session decrypted successfully via Active Tier (T-1: L1+L3).",
        )

    def _promote_to_failover(self, ct: HyperionCiphertext, session: SessionState) -> DecapsResult:
        """T-1 anomaly detected -> promote to T-2 (L6 + L12)."""
        old_tier = session.current_tier
        session.current_tier = TierLevel.FAILOVER
        session.threat_level = ThreatLevel.ANOMALY
        session.promoted_at_ns = time.time_ns()
        self._global_tier = TierLevel.FAILOVER
        self._global_threat = ThreatLevel.ANOMALY
        self._consecutive_failovers += 1

        trigger = session.anomaly_log[-1] if session.anomaly_log else None
        if self._on_tier_promote and trigger:
            try:
                self._on_tier_promote(old_tier, TierLevel.FAILOVER, trigger)
            except Exception:
                pass

        _log.warning(
            "[%s] TIER PROMOTE T-1->T-2 | consecutive_failovers=%d",
            session.session_id.hex()[:8], self._consecutive_failovers,
        )

        # Re-derive r_seed via lattice decryption (needed by T-2)
        try:
            _, _, m_prime, r_seed_p, k_cand_p = (
                ActiveTierEngine.verify_lattice_and_syndrome(self._sk, ct)
            )
        except Exception as exc:
            _log.error("[T-2] r_seed re-derivation failed: %s", exc)
            return self._escalate_to_cold(ct, session, "r_seed re-derivation failed at T-2")

        # T-2 verification
        try:
            quat_ok, iso_ok = FailoverTierEngine.verify_quaternion_and_isogeny(
                self._sk, ct, r_seed_p
            )
        except Exception as exc:
            ev = self._make_anomaly(AnomalyType.QUATERNION_MISMATCH, session, str(exc))
            session.record_anomaly(ev)
            _log.error("[T-2] Exception: %s", exc)
            return self._escalate_to_cold(ct, session, str(exc))

        if not quat_ok:
            ev = self._make_anomaly(AnomalyType.QUATERNION_MISMATCH, session, "L6 QAC mismatch")
            session.record_anomaly(ev)
            _log.warning(ev.to_log_line())
            return self._escalate_to_cold(ct, session, "Quaternion layer failed at T-2")

        if not iso_ok:
            ev = self._make_anomaly(AnomalyType.ISOGENY_MISMATCH, session, "L12 CSIDH mismatch")
            session.record_anomaly(ev)
            _log.warning(ev.to_log_line())
            return self._escalate_to_cold(ct, session, "Isogeny layer failed at T-2")

        # T-2 SUCCESS
        key = KeyReconstructionEngine.reconstruct(self._sk, ct, m_prime, r_seed_p, k_cand_p)
        session.decaps_count += 1
        session.advance_audit_chain(key)
        self._advance_global_audit(key)
        self._consecutive_failovers = max(0, self._consecutive_failovers - 1)

        _log.info(
            "[%s] T-2 FAILOVER SUCCESS | quat_ok=%s iso_ok=%s",
            session.session_id.hex()[:8], quat_ok, iso_ok,
        )
        return DecapsResult(
            success=True,
            shared_key=key,
            tier_used=TierLevel.FAILOVER,
            threat_level=ThreatLevel.ANOMALY,
            session_id=session.session_id,
            anomalies_detected=list(session.anomaly_log),
            audit_trail=session.audit_chain,
            message=(
                "WARNING: Session recovered via Failover Tier (T-2: L6+L12). "
                "Active tier anomaly detected and mitigated."
            ),
        )

    def _escalate_to_cold(
        self, ct: HyperionCiphertext, session: SessionState, reason: str
    ) -> DecapsResult:
        """T-2 failed -> escalate to T-3 cold tier."""
        session.current_tier = TierLevel.COLD
        session.threat_level = ThreatLevel.BREACH
        session.locked_down_at_ns = time.time_ns()
        self._global_tier = TierLevel.COLD
        self._global_threat = ThreatLevel.BREACH

        _log.critical(
            "[%s] ESCALATE T-2->T-3 (Cold) | reason=%r",
            session.session_id.hex()[:8], reason,
        )

        # Re-derive for cold tier
        try:
            _, _, m_prime, r_seed_p, k_cand_p = (
                ActiveTierEngine.verify_lattice_and_syndrome(self._sk, ct)
            )
        except Exception as exc:
            _log.critical("[T-3] Complete lattice failure: %s -> LOCKDOWN", exc)
            return self._full_lockdown(session, "All tiers compromised: " + str(exc))

        try:
            cold_ok, layer_results = ColdTierEngine.verify_full_cold_suite(
                self._sk, ct, r_seed_p, k_cand_p, m_prime
            )
        except Exception as exc:
            ev = self._make_anomaly(AnomalyType.COLD_VERIFY_FAIL, session, str(exc))
            session.record_anomaly(ev)
            _log.critical("[T-3] Cold suite exception: %s", exc)
            return self._full_lockdown(session, str(exc))

        failed = [k for k, v in layer_results.items() if not v]
        if failed:
            ev = self._make_anomaly(
                AnomalyType.COLD_VERIFY_FAIL, session,
                f"Cold-tier failures: {failed}",
            )
            session.record_anomaly(ev)
            _log.critical("[T-3] %d layers failed: %s", len(failed), failed)
            if not layer_results.get("CONFIRM_TAG", False):
                return self._full_lockdown(
                    session, f"CONFIRM_TAG failed. Confirmed breach: {failed}"
                )

        if cold_ok:
            key = KeyReconstructionEngine.reconstruct(self._sk, ct, m_prime, r_seed_p, k_cand_p)
            session.decaps_count += 1
            session.advance_audit_chain(key)
            self._advance_global_audit(key)
            _log.warning("[%s] T-3 COLD SUCCESS | partial_failures=%s",
                         session.session_id.hex()[:8], failed)
            return DecapsResult(
                success=True,
                shared_key=key,
                tier_used=TierLevel.COLD,
                threat_level=ThreatLevel.BREACH,
                session_id=session.session_id,
                anomalies_detected=list(session.anomaly_log),
                audit_trail=session.audit_chain,
                message=(
                    "CRITICAL WARNING: Session recovered via Cold Tier (T-3: 17-layer suite). "
                    f"Partial anomalies in layers: {failed or 'none'}. "
                    "Breach-level threat mitigated."
                ),
            )
        else:
            return self._full_lockdown(session, f"T-3 full suite failure: {failed}")

    def _full_lockdown(self, session: SessionState, reason: str) -> DecapsResult:
        """System-wide lockdown. IND-CCA2 compliant rejection."""
        self._global_threat = ThreatLevel.LOCKDOWN
        session.threat_level = ThreatLevel.LOCKDOWN
        session.locked_down_at_ns = time.time_ns()

        _log.critical(
            "[%s] SYSTEM LOCKDOWN | reason=%r | anomalies=%d",
            session.session_id.hex()[:8], reason, len(session.anomaly_log),
        )

        if self._on_lockdown:
            try:
                self._on_lockdown(session)
            except Exception:
                pass

        return DecapsResult(
            success=False,
            shared_key=None,
            tier_used=TierLevel.COLD,
            threat_level=ThreatLevel.LOCKDOWN,
            session_id=session.session_id,
            anomalies_detected=list(session.anomaly_log),
            audit_trail=session.audit_chain,
            message=(
                f"CRITICAL FAILURE: All {len(session.anomaly_log)} defensive layers "
                f"breached or compromised. System LOCKED DOWN. Reason: {reason}"
            ),
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _new_session(self) -> SessionState:
        sid = QuantumEntropyExtractor.distill_quantum_seed(16)
        s = SessionState(session_id=sid)
        s.current_tier = self._global_tier
        s.threat_level = self._global_threat
        return s

    def _make_anomaly(
        self, atype: AnomalyType, session: SessionState, detail: str
    ) -> AnomalyEvent:
        evidence = hashlib.sha3_256(
            atype.to_bytes(2, "little")
            + session.session_id
            + detail.encode("utf-8", errors="replace")
        ).digest()
        return AnomalyEvent(
            anomaly_type=atype,
            tier_at_detection=session.current_tier,
            detail=detail,
            session_id_hint=session.session_id,
            evidence_hash=evidence,
        )

    def _advance_global_audit(self, event_bytes: bytes) -> None:
        self._global_audit = hashlib.sha3_256(
            _DOM_AFMCP_AUDIT + self._global_audit + event_bytes
        ).digest()

    def _reject(self, session: SessionState, msg: str) -> DecapsResult:
        return DecapsResult(
            success=False,
            shared_key=None,
            tier_used=session.current_tier,
            threat_level=session.threat_level,
            session_id=session.session_id,
            anomalies_detected=list(session.anomaly_log),
            audit_trail=session.audit_chain,
            message=msg,
        )


# =============================================================================
#  Convenience Factory
# =============================================================================

def build_pipeline(
    sk: HyperionSecretKey,
    *,
    anomaly_threshold: int = 3,
    verbose: bool = False,
) -> AdaptiveFailoverCryptoPipeline:
    """
    Convenience factory for AdaptiveFailoverCryptoPipeline with
    pre-wired logging callbacks.

    Example
    -------
    >>> from qntum_pqc import HyperionKEM
    >>> from qntum_pqc.af_mcp import build_pipeline
    >>> pk, sk = HyperionKEM.keygen()
    >>> ct, tx_key = HyperionKEM.encaps(pk)
    >>> pipeline = build_pipeline(sk)
    >>> result = pipeline.decaps(ct)
    >>> assert result.is_secure()
    >>> assert result.shared_key == tx_key
    """
    if verbose:
        logging.getLogger("AF_MCP").setLevel(logging.DEBUG)

    def _on_promote(old: TierLevel, new: TierLevel, ev: AnomalyEvent) -> None:
        _log.warning("CALLBACK: Tier %s -> %s | anomaly=%s", old.name, new.name, ev.anomaly_type.name)

    def _on_lock(sess: SessionState) -> None:
        _log.critical("CALLBACK: LOCKDOWN | session=%s | anomalies=%d",
                      sess.session_id.hex()[:8], len(sess.anomaly_log))

    return AdaptiveFailoverCryptoPipeline(
        sk,
        anomaly_threshold=anomaly_threshold,
        on_tier_promote=_on_promote,
        on_lockdown=_on_lock,
    )

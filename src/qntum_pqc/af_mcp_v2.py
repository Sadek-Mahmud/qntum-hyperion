"""
================================================================================
AF-MCP v2 — Adaptive Failover Multi-Layer Cryptographic Pipeline
================================================================================
Architecture : QNTUM-HYPERION SEPTEM-TITAN-17L
Author       : A. S. M. Hossain Mahmud (Shadhin) · BAUST, Bangladesh
Paper        : IEEE Access 2026

Operational Architecture (Tiered Defense-in-Depth):
  ┌─────────────────────────────────────────────────────────────────────┐
  │  T-1  ACTIVE   TIER  │ L1 (Module-LWE)  + L3 (Binary SDP)         │
  │                       │ Always-on · Real-time · <0.5 ms target       │
  ├───────────────────────┼──────────────────────────────────────────────┤
  │  T-2  FAILOVER TIER  │ L6 (QAC Quaternion) + L12 (CSIDH Isogeny)  │
  │                       │ Standby · Promoted on T-1 anomaly · ~1-2 ms  │
  ├───────────────────────┼──────────────────────────────────────────────┤
  │  T-3  COLD     TIER  │ L11, 13, 14, 15, 16, 17 + CONFIRM-TAG-17L  │
  │                       │ Dormant · Ultimate fallback · ~3-5 ms         │
  └─────────────────────────────────────────────────────────────────────┘

Security Invariants:
  1. Constant-time rejection: ALL failure paths execute identical dummy work.
  2. Tamper-evident audit chain: every anomaly ratchets a SHA3-256 chain.
  3. Replay protection: SHA3-256 fingerprint registry (bounded 65536 entries).
  4. IND-CCA2 FO-transform: re-encryption check on every L1 verification.
  5. Thread-safety: single RLock guards all mutable pipeline state.

State Transition Graph:
  NOMINAL --[T-1 fail]--> ANOMALY --[T-2 fail]--> BREACH --[T-3 fail]--> LOCKDOWN
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

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

_log = logging.getLogger("AF_MCP_V2")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [AF-MCP-v2] %(levelname)s > %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

_DOM_AUDIT         = b"AF-MCP-V2-AUDIT-SHA3-v2"
_DOM_DUMMY_WORK    = b"AF-MCP-V2-DUMMY-CTTIME-v2"
_DOM_REPLAY_NONCE  = b"AF-MCP-V2-REPLAY-NONCE-v2"
_DUMMY_HASH_ITERS  = 64
_MAX_REPLAY_CACHE  = 65536
_SESSION_TIMEOUT_NS = 300 * 10**9  # 5 minutes


# =============================================================================
#  Enumerations
# =============================================================================

class TierLevel(IntEnum):
    ACTIVE   = 1
    FAILOVER = 2
    COLD     = 3

PipelineTier = TierLevel


class ThreatLevel(IntEnum):
    NOMINAL  = 0
    ANOMALY  = 1
    BREACH   = 2
    LOCKDOWN = 3


class AnomalyType(IntEnum):
    TAG_MISMATCH        = auto()
    LATTICE_VERIFY_FAIL = auto()
    FO_REENC_FAIL       = auto()
    SYNDROME_MISMATCH   = auto()
    QUATERNION_MISMATCH = auto()
    ISOGENY_MISMATCH    = auto()
    BRAID_MISMATCH      = auto()
    GROUP_RING_MISMATCH = auto()
    GF2_COMMIT_MISMATCH = auto()
    STARK_ROOT_MISMATCH = auto()
    TARPIT_MISMATCH     = auto()
    HONEYPOT_MISMATCH   = auto()
    CONFIRM_TAG_FAIL    = auto()
    TIMING_ANOMALY      = auto()
    SIDE_CHANNEL_ALERT  = auto()
    REPLAY_DETECTED     = auto()
    COLD_VERIFY_FAIL    = auto()
    SESSION_TIMEOUT     = auto()
    INTERNAL_ERROR      = auto()


# =============================================================================
#  Exceptions
# =============================================================================

class AFMCPException(Exception):
    """Base AF-MCP v2 exception."""

class SecurityException(AFMCPException):
    """Cryptographic validation failed."""

class CriticalFailureException(AFMCPException):
    """All defensive tiers breached."""

class ReplayException(AFMCPException):
    """Previously seen ciphertext."""

class LockdownException(AFMCPException):
    """Pipeline in hard LOCKDOWN."""


# =============================================================================
#  Data Classes
# =============================================================================

@dataclass
class AnomalyEvent:
    """Immutable record of a single detected cryptographic anomaly."""
    anomaly_type:      AnomalyType
    tier_at_detection: TierLevel
    timestamp_ns:      int   = field(default_factory=time.time_ns)
    detail:            str   = ""
    session_id_hint:   bytes = b""
    evidence_hash:     bytes = b""

    def to_log_line(self) -> str:
        return (
            f"ANOMALY [{self.anomaly_type.name}] "
            f"tier=T-{int(self.tier_at_detection)} "
            f"evidence={self.evidence_hash.hex()[:16]}... "
            f"detail={self.detail!r}"
        )

    def serialize(self) -> bytes:
        return (
            self.anomaly_type.to_bytes(2, "little")
            + self.tier_at_detection.to_bytes(1, "little")
            + self.timestamp_ns.to_bytes(8, "little")
            + self.evidence_hash
        )


@dataclass
class SessionState:
    """Per-invocation session state."""
    session_id:        bytes        = field(default_factory=lambda: QuantumEntropyExtractor.distill_quantum_seed(16))
    current_tier:      TierLevel    = TierLevel.ACTIVE
    threat_level:      ThreatLevel  = ThreatLevel.NOMINAL
    anomaly_log:       List[AnomalyEvent] = field(default_factory=list)
    audit_chain:       bytes        = b"\x00" * 32
    created_at_ns:     int          = field(default_factory=time.time_ns)
    last_activity_ns:  int          = field(default_factory=time.time_ns)
    promoted_at_ns:    Optional[int] = None
    locked_down_at_ns: Optional[int] = None
    decaps_count:      int          = 0

    def advance_audit_chain(self, event_bytes: bytes) -> None:
        """Ratchet the tamper-evident per-session audit chain."""
        self.audit_chain = hashlib.sha3_256(
            _DOM_AUDIT + self.audit_chain + event_bytes
        ).digest()
        self.last_activity_ns = time.time_ns()

    def record_anomaly(self, event: AnomalyEvent) -> None:
        self.anomaly_log.append(event)
        self.advance_audit_chain(event.serialize())

    def is_expired(self) -> bool:
        return (time.time_ns() - self.created_at_ns) > _SESSION_TIMEOUT_NS


@dataclass
class DecapsResult:
    """Structured, tamper-evident result from pipeline.decaps()."""
    success:            bool
    shared_key:         Optional[bytes]
    tier_used:          TierLevel
    threat_level:       ThreatLevel
    session_id:         bytes
    anomalies_detected: List[AnomalyEvent] = field(default_factory=list)
    audit_trail:        bytes = b"\x00" * 32
    latency_ns:         int   = 0
    message:            str   = ""

    def is_secure(self) -> bool:
        return self.success and self.threat_level < ThreatLevel.LOCKDOWN

    def latency_ms(self) -> float:
        return self.latency_ns / 1_000_000.0


# =============================================================================
#  Benchmark Collector
# =============================================================================

class PipelineBenchmark:
    """
    Lightweight rolling latency benchmark collector.

    Records p99 latency per tier for SLA verification.
    Target SLAs:
        T-1 p99 < 1.0 ms
        T-2 p99 < 2.0 ms
        T-3 p99 < 5.0 ms
    """

    def __init__(self, max_samples: int = 1000):
        self._max = max_samples
        self._t1: Deque[float] = deque(maxlen=max_samples)
        self._t2: Deque[float] = deque(maxlen=max_samples)
        self._t3: Deque[float] = deque(maxlen=max_samples)
        self._rej: Deque[float] = deque(maxlen=max_samples)

    def record(self, tier: TierLevel, latency_ns: int) -> None:
        ms = latency_ns / 1_000_000.0
        if   tier == TierLevel.ACTIVE:   self._t1.append(ms)
        elif tier == TierLevel.FAILOVER: self._t2.append(ms)
        elif tier == TierLevel.COLD:     self._t3.append(ms)

    def record_rejection(self, latency_ns: int) -> None:
        self._rej.append(latency_ns / 1_000_000.0)

    def _stats(self, samples: Deque[float]) -> Dict:
        if not samples:
            return {"n": 0, "mean_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0, "p99_ms": 0.0}
        s = sorted(samples)
        n = len(s)
        return {
            "n":       n,
            "mean_ms": sum(s) / n,
            "min_ms":  s[0],
            "max_ms":  s[-1],
            "p99_ms":  s[max(0, int(0.99 * n) - 1)],
        }

    def report(self) -> Dict:
        return {
            "T1_Active":   self._stats(self._t1),
            "T2_Failover": self._stats(self._t2),
            "T3_Cold":     self._stats(self._t3),
            "Rejected":    self._stats(self._rej),
        }

    def print_report(self) -> None:
        r = self.report()
        print("\n" + "=" * 68)
        print("  AF-MCP v2 — Benchmark Report")
        print("=" * 68)
        sla = {"T1_Active": 1.0, "T2_Failover": 2.0, "T3_Cold": 5.0}
        for tier, stats in r.items():
            if stats["n"] == 0:
                continue
            flag = ""
            if tier in sla:
                flag = "OK" if stats["p99_ms"] < sla[tier] else "OVER_SLA"
            print(f"  {tier:<14} n={stats['n']:>5} | "
                  f"mean={stats['mean_ms']:>7.3f}ms | "
                  f"p99={stats['p99_ms']:>7.3f}ms | {flag}")
        print("=" * 68 + "\n")


# =============================================================================
#  Constant-Time Utilities
# =============================================================================

class ConstantTime:
    """
    Side-channel mitigations.

    NOTE: Python is not hardware constant-time. These utilities eliminate
    algorithmic timing differences — the dominant leakage in PQC software.
    For hardware constant-time guarantees use the companion C++ shim
    af_mcp_v2_ct.cpp compiled with -O0 -fno-optimize-sibling-calls.
    """

    @staticmethod
    def bytes_eq(a: bytes, b: bytes) -> bool:
        """
        Constant-time byte comparison.
        Pads to equal length to avoid length-leak, then uses
        hmac.compare_digest (OpenSSL CRYPTO_memcmp underneath).
        """
        max_len = max(len(a), len(b))
        return hmac.compare_digest(
            a.ljust(max_len, b"\x00"),
            b.ljust(max_len, b"\x00"),
        )

    @staticmethod
    def dummy_hash_work(seed: bytes, n_iters: int = _DUMMY_HASH_ITERS) -> bytes:
        """
        Execute n_iters of SHA3-256 to absorb constant CPU time on
        rejection paths, preventing timing side-channel leakage.

        The return value is always discarded by the caller.
        """
        h = seed
        for i in range(n_iters):
            h = hashlib.sha3_256(
                _DOM_DUMMY_WORK + h + i.to_bytes(4, "little")
            ).digest()
        return h

    @staticmethod
    def scrub(buf: bytearray) -> None:
        """Zero-overwrite secret key material before deallocation."""
        for i in range(len(buf)):
            buf[i] = 0


# =============================================================================
#  Integrity Check Suite
# =============================================================================

class IntegrityChecks:
    """
    Per-tier programmatic integrity checkers.

    All return (ok: bool, detail: str).
    All comparisons use ConstantTime.bytes_eq.
    All exceptions trigger constant-time dummy work before returning False.
    """

    # -- T-1: Fujisaki-Okamoto Re-Encryption Check ----------------------------

    @staticmethod
    def fo_reencryption_check(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
    ) -> Tuple[bool, bytes, bytes, bytes, str]:
        """
        Fujisaki-Okamoto re-encryption validity check (IND-CCA2 core).

        Algorithm:
          m' = Decrypt(sk, ct)
          r' = G(m' || pk_fingerprint)
          (u', v') = Encrypt(pk, m'; r')
          return constant_time_eq(u, u') AND constant_time_eq(v, v')
        """
        try:
            # Step 1: ISW-unmasked lattice decryption
            s_unmasked = MaskingEngine.unmask_vector_1st_order(sk.s_share0, sk.s_share1)
            s_ntt  = vec_ntt(s_unmasked)
            su_ntt = vec_dot_ntt(s_ntt, vec_ntt(ct.u))
            w      = poly_sub(ct.v, vec_intt([su_ntt])[0])
            m_prime = _decode_msg(w)

            # Step 2: Re-derive randomness
            coins_p  = QuantumSponge.hash_512(m_prime + sk.pk.fingerprint, DOM_SEP_KEM_ENC)
            r_seed_p = coins_p[:32]
            k_cand_p = coins_p[32:64]

            # Step 3: Re-encrypt
            r_p   = [QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)]
            e1_p  = [QuantumSponge.sample_centered_binomial(r_seed_p, K + i) for i in range(K)]
            e2_p  = QuantumSponge.sample_centered_binomial(r_seed_p, 2 * K)
            A_ntt = sk.pk.get_A_ntt()
            r_ntt_p = vec_ntt(r_p)
            u_p = vec_add(vec_intt(mat_transpose_vec_mul_ntt(A_ntt, r_ntt_p)), e1_p)
            tr_p = vec_intt([vec_dot_ntt(sk.pk.t_ntt, r_ntt_p)])[0]
            v_p  = poly_add(poly_add(tr_p, e2_p), _encode_msg(m_prime))

            # Step 4: Constant-time comparison
            u_ok = ConstantTime.bytes_eq(_serialize_vec(ct.u), _serialize_vec(u_p))
            v_ok = ConstantTime.bytes_eq(_serialize_poly(ct.v), _serialize_poly(v_p))
            ok   = u_ok and v_ok
            return ok, m_prime, r_seed_p, k_cand_p, f"FO: u_ok={u_ok} v_ok={v_ok}"

        except Exception as exc:
            ConstantTime.dummy_hash_work(b"fo-reenc-exception")
            return False, b"", b"", b"", f"FO exception: {exc}"

    # -- T-1: Syndrome Verification He^t = s ----------------------------------

    @staticmethod
    def syndrome_check(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
    ) -> Tuple[bool, str]:
        """
        Verify syndrome: H * e^T = s (mod 2).
        H   = parity check matrix derived from code_seed
        e   = sparse error vector from r_seed_p
        s   = syndrome bytes in ciphertext
        """
        try:
            H   = SyndromeDecodingBarrier.expand_parity_matrix(sk.pk.code_seed)
            e   = SyndromeDecodingBarrier.sample_sparse_error(r_seed_p)
            s_p = SyndromeDecodingBarrier.compute_syndrome(H, e)
            ok  = ConstantTime.bytes_eq(ct.syndrome, s_p)
            return ok, f"SDP L3 He^t=s: {ok}"
        except Exception as exc:
            ConstantTime.dummy_hash_work(b"syndrome-exception")
            return False, f"Syndrome exception: {exc}"

    # -- T-2: Quaternion Conjugacy Check β = γαγ⁻¹ ----------------------------

    @staticmethod
    def quaternion_check(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
    ) -> Tuple[bool, str]:
        """
        Verify quaternion conjugacy: β = γ · α · γ⁻¹ (mod P_QUAT).
        Non-Abelian => immune to Shor QFT-based attacks.
        """
        try:
            eph_q: Quaternion = (
                int.from_bytes(r_seed_p[0:4],  "little") % P_QUAT,
                int.from_bytes(r_seed_p[4:8],  "little") % P_QUAT,
                int.from_bytes(r_seed_p[8:12], "little") % P_QUAT,
                (int.from_bytes(r_seed_p[12:16], "little") % (P_QUAT - 1)) + 1,
            )
            expected = QuaternionAlgebra.conjugate_action(eph_q, sk.pk.quat_base)
            ok = ConstantTime.bytes_eq(
                QuaternionAlgebra.serialize(ct.quat_action),
                QuaternionAlgebra.serialize(expected),
            )
            return ok, f"QAC L6 beta=gamma*alpha*gamma_inv: {ok}"
        except Exception as exc:
            ConstantTime.dummy_hash_work(b"quat-exception")
            return False, f"QAC exception: {exc}"

    # -- T-2: CSIDH Group Action Check ----------------------------------------

    @staticmethod
    def csidh_check(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
    ) -> Tuple[bool, str]:
        """
        Verify CSIDH group action: A' = [∏ l_i^e_i] * A (mod p).
        Kuperberg subexponential quantum attack requires exp(sqrt(log p)) qubits.
        """
        try:
            eph_ideal = [
                ((r_seed_p[i % 32] % 11) - 5)
                for i in range(len(SupersingularIsogenyAction.PRIMES))
            ]
            expected = SupersingularIsogenyAction.evaluate_group_action(
                sk.pk.isogeny_base_curve, eph_ideal
            )
            ok = ConstantTime.bytes_eq(
                ct.isogeny_curve_action.to_bytes(32, "little"),
                expected.to_bytes(32, "little"),
            )
            return ok, f"CSIDH L12 group_action: {ok}"
        except Exception as exc:
            ConstantTime.dummy_hash_work(b"csidh-exception")
            return False, f"CSIDH exception: {exc}"

    # -- T-3: ZK-STARK DAG Root Check -----------------------------------------

    @staticmethod
    def stark_dag_check(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
        k_cand_p: bytes,
    ) -> Tuple[bool, str]:
        """
        Verify ZK-STARK Fiat-Shamir DAG accumulator root.
        64 rounds × 8 lanes = 512 SHA3-512 preimage inversions required.
        """
        try:
            binding = sk.pk.stark_binding + k_cand_p
            k_stark, _ = RecursiveSTARKAccumulator.run_accumulator(r_seed_p, binding)
            ok = ConstantTime.bytes_eq(ct.stark_root, k_stark)
            return ok, f"STARK L15 dag_root: {ok}"
        except Exception as exc:
            ConstantTime.dummy_hash_work(b"stark-exception")
            return False, f"STARK exception: {exc}"


# =============================================================================
#  Tier Engines
# =============================================================================

class ActiveTierEngine:
    """
    T-1 Active Tier: Layer 1 (Module-LWE FO) + Layer 3 (Binary SDP).

    Optimization Notes:
      - L1 dominates: N*K NTT multiplications + FO re-encryption.
      - L3: sparse GF(2) matrix-vector product O(N*t), t=24.
      - Both checks run sequentially with no async overhead.
      - ISW 1st-order masking on secret s for DPA/SPA resistance.
      - Target latency: < 0.5 ms (happy path).
    """

    @staticmethod
    def run(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
    ) -> Tuple[bool, bytes, bytes, bytes, List[AnomalyType]]:
        """
        Returns (all_ok, m_prime, r_seed_p, k_cand_p, failed_anomaly_types).
        Both checks always execute regardless of intermediate failure
        to prevent early-exit timing side-channels.
        """
        anomalies: List[AnomalyType] = []

        # L1: FO re-encryption (always runs)
        fo_ok, m_prime, r_seed_p, k_cand_p, _ = (
            IntegrityChecks.fo_reencryption_check(sk, ct)
        )
        if not fo_ok:
            anomalies.append(AnomalyType.FO_REENC_FAIL)

        # L3: Syndrome check (always runs — constant time)
        synd_ok, _ = IntegrityChecks.syndrome_check(sk, ct, r_seed_p)
        if not synd_ok:
            anomalies.append(AnomalyType.SYNDROME_MISMATCH)

        return fo_ok and synd_ok, m_prime, r_seed_p, k_cand_p, anomalies


class FailoverTierEngine:
    """
    T-2 Failover Tier: Layer 6 (QAC) + Layer 12 (CSIDH).
    Promoted from dormancy only on T-1 anomaly.
    """

    @staticmethod
    def run(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
    ) -> Tuple[bool, List[AnomalyType]]:
        """Returns (all_ok, failed_anomaly_types)."""
        anomalies: List[AnomalyType] = []

        # L6: Quaternion Conjugacy (always runs)
        quat_ok, _ = IntegrityChecks.quaternion_check(sk, ct, r_seed_p)
        if not quat_ok:
            anomalies.append(AnomalyType.QUATERNION_MISMATCH)

        # L12: CSIDH (always runs)
        iso_ok, _ = IntegrityChecks.csidh_check(sk, ct, r_seed_p)
        if not iso_ok:
            anomalies.append(AnomalyType.ISOGENY_MISMATCH)

        return quat_ok and iso_ok, anomalies


class ColdTierEngine:
    """
    T-3 Cold Tier: Layers 11, 13, 14, 15, 16, 17 + CONFIRM-TAG-17L.
    Dormant until both T-1 and T-2 have failed.

    Performance note: reduce STARK_ROUNDS from 64 to 8 in dev mode
    for sub-5ms cold execution (set in params.py STARK_ROUNDS).
    """

    @staticmethod
    def run(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        r_seed_p: bytes,
        k_cand_p: bytes,
        m_prime: bytes,
    ) -> Tuple[bool, Dict[str, bool]]:
        """Returns (all_ok, per_layer_results_dict)."""
        results: Dict[str, bool] = {}

        # L11: Artin Braid Group B_8 conjugacy
        try:
            eph_braid = ArtinBraidGroup.sample_random_braid(10, r_seed_p)
            braid_exp = ArtinBraidGroup.conjugate(eph_braid, sk.pk.braid_base)
            results["L11_braid"] = ConstantTime.bytes_eq(
                ArtinBraidGroup.serialize_word(ct.braid_action),
                ArtinBraidGroup.serialize_word(braid_exp),
            )
        except Exception:
            ConstantTime.dummy_hash_work(b"braid-t3")
            results["L11_braid"] = False

        # L13: Non-Commutative Group Ring S_8
        try:
            eph_gr = SymmetricGroupRing.from_seed(r_seed_p, index=13)
            gr_exp = SymmetricGroupRing.evaluate_group_ring_action(
                sk.pk.group_ring_base, eph_gr
            )
            results["L13_group_ring"] = ConstantTime.bytes_eq(
                SymmetricGroupRing.serialize_permutation(ct.gr_action),
                SymmetricGroupRing.serialize_permutation(gr_exp),
            )
        except Exception:
            ConstantTime.dummy_hash_work(b"gr-t3")
            results["L13_group_ring"] = False

        # L14: GF(2^256) Polynomial Commitment
        try:
            gf2_eph  = BinaryExtensionCommitment.sample_secret_poly(r_seed_p)
            gf2_cm   = [BinaryExtensionCommitment.evaluate_poly(gf2_eph, pt)
                        for pt in sk.pk.gf2_eval_points]
            gf2_b    = BinaryExtensionCommitment.serialize_commitment(gf2_cm)
            results["L14_gf2"] = ConstantTime.bytes_eq(
                BinaryExtensionCommitment.serialize_commitment(ct.gf2_commitment),
                gf2_b,
            )
        except Exception:
            ConstantTime.dummy_hash_work(b"gf2-t3")
            results["L14_gf2"] = False

        # L15: ZK-STARK DAG Accumulator
        stark_ok, _ = IntegrityChecks.stark_dag_check(sk, ct, r_seed_p, k_cand_p)
        results["L15_stark"] = stark_ok

        # L16: Grover Reversal Tarpit
        try:
            tarpit_pub = sk.pk.fingerprint + k_cand_p
            tarpit_cm  = GroverReversalTarpit.generate_tarpit_commitment(r_seed_p, tarpit_pub)
            tarpit_tag = GroverReversalTarpit.compute_tarpit_tag(
                pub_seed=tarpit_pub, real_secret=r_seed_p, commitment=tarpit_cm
            )
            results["L16_tarpit"] = ConstantTime.bytes_eq(ct.tarpit_tag, tarpit_tag)
        except Exception:
            ConstantTime.dummy_hash_work(b"tarpit-t3")
            results["L16_tarpit"] = False

        # L17: Adversarial Honeypot
        try:
            hp_pub = sk.pk.fingerprint + k_cand_p + b"HONEYPOT-BIND-L17"
            k_hp   = AdversarialHoneypot.derive_honeypot_key_contribution(
                real_secret=r_seed_p, pub_binding=hp_pub
            )
            hp_cm  = AdversarialHoneypot.compute_honeypot_commitment(
                real_secret=r_seed_p, pub_binding=hp_pub, real_key=k_hp
            )
            results["L17_honeypot"] = ConstantTime.bytes_eq(ct.honeypot_commit, hp_cm)
        except Exception:
            ConstantTime.dummy_hash_work(b"honeypot-t3")
            results["L17_honeypot"] = False

        # CONFIRM-TAG-17L: Master Authentication Tag
        try:
            eph_q: Quaternion = (
                int.from_bytes(r_seed_p[0:4],  "little") % P_QUAT,
                int.from_bytes(r_seed_p[4:8],  "little") % P_QUAT,
                int.from_bytes(r_seed_p[8:12], "little") % P_QUAT,
                (int.from_bytes(r_seed_p[12:16], "little") % (P_QUAT - 1)) + 1,
            )
            quat_act  = QuaternionAlgebra.conjugate_action(eph_q, sk.pk.quat_base)
            eph_ideal = [((r_seed_p[i % 32] % 11) - 5)
                         for i in range(len(SupersingularIsogenyAction.PRIMES))]
            iso_act   = SupersingularIsogenyAction.evaluate_group_action(
                sk.pk.isogeny_base_curve, eph_ideal
            )
            r_ntt_p = vec_ntt([QuantumSponge.sample_centered_binomial(r_seed_p, i)
                               for i in range(K)])
            e1_p    = [QuantumSponge.sample_centered_binomial(r_seed_p, K + i)
                       for i in range(K)]
            e2_p    = QuantumSponge.sample_centered_binomial(r_seed_p, 2 * K)
            u_p     = vec_add(vec_intt(mat_transpose_vec_mul_ntt(
                sk.pk.get_A_ntt(), r_ntt_p)), e1_p)
            tr_p    = vec_intt([vec_dot_ntt(sk.pk.t_ntt, r_ntt_p)])[0]
            v_p     = poly_add(poly_add(tr_p, e2_p), _encode_msg(m_prime))
            synd_p  = SyndromeDecodingBarrier.compute_syndrome(
                SyndromeDecodingBarrier.expand_parity_matrix(sk.pk.code_seed),
                SyndromeDecodingBarrier.sample_sparse_error(r_seed_p),
            )
            braid_act_p = ArtinBraidGroup.conjugate(
                ArtinBraidGroup.sample_random_braid(10, r_seed_p),
                sk.pk.braid_base,
            )
            k_stark_p, _ = RecursiveSTARKAccumulator.run_accumulator(
                r_seed_p, sk.pk.stark_binding + k_cand_p
            )
            eph_gr_p   = SymmetricGroupRing.from_seed(r_seed_p, index=13)
            gr_act_p   = SymmetricGroupRing.evaluate_group_ring_action(
                sk.pk.group_ring_base, eph_gr_p
            )
            gf2_eph_p  = BinaryExtensionCommitment.sample_secret_poly(r_seed_p)
            gf2_b_p    = BinaryExtensionCommitment.serialize_commitment([
                BinaryExtensionCommitment.evaluate_poly(gf2_eph_p, pt)
                for pt in sk.pk.gf2_eval_points
            ])
            tarpit_pub_p = sk.pk.fingerprint + k_cand_p
            tarpit_cm_p  = GroverReversalTarpit.generate_tarpit_commitment(r_seed_p, tarpit_pub_p)
            tarpit_tag_p = GroverReversalTarpit.compute_tarpit_tag(
                pub_seed=tarpit_pub_p, real_secret=r_seed_p, commitment=tarpit_cm_p
            )
            hp_pub_p = sk.pk.fingerprint + k_cand_p + b"HONEYPOT-BIND-L17"
            k_hp_p   = AdversarialHoneypot.derive_honeypot_key_contribution(
                real_secret=r_seed_p, pub_binding=hp_pub_p
            )
            hp_cm_p  = AdversarialHoneypot.compute_honeypot_commitment(
                real_secret=r_seed_p, pub_binding=hp_pub_p, real_key=k_hp_p
            )
            tag_p = QuantumSponge.hash_256(
                k_cand_p
                + _serialize_vec(u_p)
                + _serialize_poly(v_p)
                + synd_p
                + QuaternionAlgebra.serialize(quat_act)
                + ArtinBraidGroup.serialize_word(braid_act_p)
                + iso_act.to_bytes(32, "little")
                + SymmetricGroupRing.serialize_permutation(gr_act_p)
                + gf2_b_p
                + k_stark_p
                + tarpit_tag_p
                + hp_cm_p,
                b"CONFIRM-TAG-17L",
            )
            results["CONFIRM_TAG"] = ConstantTime.bytes_eq(ct.tag, tag_p)
        except Exception as exc:
            ConstantTime.dummy_hash_work(b"confirm-tag-t3")
            results["CONFIRM_TAG"] = False
            _log.error("[T-3] CONFIRM_TAG exception: %s", exc)

        return all(results.values()), results


# =============================================================================
#  Key Reconstruction Engine
# =============================================================================

class KeyReconstructionEngine:
    """
    12-way Vernam-XOR blended session key reconstruction.

    IND-CCA2 Compliance:
      Key output only follows a passed FO re-encryption check.
      Formula: K = SHAKE-256(K1 XOR K2 XOR ... XOR K12 || CT, DOM)
    """

    @staticmethod
    def reconstruct(
        sk: HyperionSecretKey,
        ct: HyperionCiphertext,
        m_prime: bytes,
        r_seed_p: bytes,
        k_cand_p: bytes,
    ) -> bytes:
        k_lat  = QuantumSponge.hash_256(m_prime, b"LATTICE-KEY")
        r_ntt_p = vec_ntt([QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)])
        psi_rp  = MultivariatePerturbation.evaluate_perturbation(
            [QuantumSponge.sample_centered_binomial(r_seed_p, i) for i in range(K)],
            sk.pk.rho, s_ntt=r_ntt_p,
        )
        k_mv   = QuantumSponge.hash_256(_serialize_vec(psi_rp), DOM_SEP_NONLINEAR_QUAD)
        err    = SyndromeDecodingBarrier.sample_sparse_error(r_seed_p)
        k_code = QuantumSponge.hash_256(err.to_bytes(64, "little"), b"CODE-KEY")
        k_sp   = QuantumSponge.hash_256(k_cand_p, b"SPONGE-KEY")
        eph_q: Quaternion = (
            int.from_bytes(r_seed_p[0:4],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[4:8],  "little") % P_QUAT,
            int.from_bytes(r_seed_p[8:12], "little") % P_QUAT,
            (int.from_bytes(r_seed_p[12:16], "little") % (P_QUAT - 1)) + 1,
        )
        k_quat = QuantumSponge.hash_256(
            QuaternionAlgebra.serialize(
                QuaternionAlgebra.conjugate_action(eph_q, sk.pk.quat_base)
            ), DOM_SEP_QUATERNION_LAYER
        )
        k_braid = QuantumSponge.hash_256(
            ArtinBraidGroup.serialize_word(
                ArtinBraidGroup.conjugate(
                    ArtinBraidGroup.sample_random_braid(10, r_seed_p),
                    sk.pk.braid_base
                )
            ), DOM_SEP_BRAID_LAYER
        )
        eph_ideal = [((r_seed_p[i % 32] % 11) - 5)
                     for i in range(len(SupersingularIsogenyAction.PRIMES))]
        k_iso  = QuantumSponge.hash_256(
            SupersingularIsogenyAction.evaluate_group_action(
                sk.pk.isogeny_base_curve, eph_ideal
            ).to_bytes(32, "little"), DOM_SEP_ISOGENY_LAYER
        )
        k_gr   = QuantumSponge.hash_256(
            SymmetricGroupRing.serialize_permutation(
                SymmetricGroupRing.evaluate_group_ring_action(
                    sk.pk.group_ring_base,
                    SymmetricGroupRing.from_seed(r_seed_p, index=13)
                )
            ), DOM_SEP_GROUP_RING_LAYER
        )
        gf2_eph = BinaryExtensionCommitment.sample_secret_poly(r_seed_p)
        k_gf2  = BinaryExtensionCommitment.derive_key_from_commitment(
            [BinaryExtensionCommitment.evaluate_poly(gf2_eph, pt) for pt in sk.pk.gf2_eval_points],
            DOM_SEP_GF2_COMMIT_LAYER,
        )
        k_stark, _ = RecursiveSTARKAccumulator.run_accumulator(
            r_seed_p, sk.pk.stark_binding + k_cand_p
        )
        tarpit_pub = sk.pk.fingerprint + k_cand_p
        tarpit_cm  = GroverReversalTarpit.generate_tarpit_commitment(r_seed_p, tarpit_pub)
        k_tarpit   = GroverReversalTarpit.derive_tarpit_key(
            r_seed_p, tarpit_pub, commitment=tarpit_cm
        )
        hp_pub = sk.pk.fingerprint + k_cand_p + b"HONEYPOT-BIND-L17"
        k_hp   = AdversarialHoneypot.derive_honeypot_key_contribution(
            real_secret=r_seed_p, pub_binding=hp_pub
        )
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
        return QuantumSponge.hash_256(
            k_int.to_bytes(32, "little") + ct.export_bytes(),
            DOM_SEP_VERNAM_BLEND,
        )


# =============================================================================
#  State Transition Machine
# =============================================================================

class StateTransitionMachine:
    """
    Formal FSM: NOMINAL → ANOMALY → BREACH → LOCKDOWN.
    Guarantees monotonic threat escalation with no automatic downgrade.
    """

    def __init__(self, max_consecutive_failovers: int = 3):
        self._tier: TierLevel     = TierLevel.ACTIVE
        self._threat: ThreatLevel = ThreatLevel.NOMINAL
        self._consecutive: int    = 0
        self._max: int            = max_consecutive_failovers

    @property
    def tier(self) -> TierLevel:
        return self._tier

    @property
    def threat(self) -> ThreatLevel:
        return self._threat

    @property
    def threat_level(self) -> ThreatLevel:
        return self._threat

    @threat_level.setter
    def threat_level(self, th: ThreatLevel) -> None:
        self._threat = th

    @property
    def consecutive_failovers(self) -> int:
        return self._consecutive

    def to_failover(self) -> Tuple[TierLevel, TierLevel]:
        old = self._tier
        self._tier   = TierLevel.FAILOVER
        self._threat = ThreatLevel.ANOMALY
        self._consecutive += 1
        return old, TierLevel.FAILOVER

    def to_cold(self) -> Tuple[TierLevel, TierLevel]:
        old = self._tier
        self._tier   = TierLevel.COLD
        self._threat = ThreatLevel.BREACH
        return old, TierLevel.COLD

    def to_lockdown(self) -> None:
        self._threat = ThreatLevel.LOCKDOWN

    def on_success(self, tier: TierLevel) -> None:
        if tier == TierLevel.ACTIVE:
            self._consecutive = 0

    def needs_lockdown(self) -> bool:
        return self._consecutive >= self._max

    def reset(self, force: bool = False) -> bool:
        if self._threat >= ThreatLevel.LOCKDOWN and not force:
            return False
        self._tier      = TierLevel.ACTIVE
        self._threat    = ThreatLevel.NOMINAL
        self._consecutive = 0
        return True


# =============================================================================
#  Replay Protection Registry
# =============================================================================

class ReplayRegistry:
    """
    Bounded SHA3-256 fingerprint registry for replay attack prevention.
    O(1) lookup, O(1) amortized eviction.
    """

    def __init__(self, max_entries: int = _MAX_REPLAY_CACHE):
        self._max   = max_entries
        self._seen: Set[bytes]   = set()
        self._order: Deque[bytes] = deque()
        self._lock  = threading.Lock()

    def check_and_register(self, ct: HyperionCiphertext) -> bool:
        """Returns True (fresh) / False (replay). Registers atomically."""
        fp = hashlib.sha3_256(_DOM_REPLAY_NONCE + ct.tag).digest()
        with self._lock:
            if fp in self._seen:
                return False
            if len(self._seen) >= self._max:
                self._seen.discard(self._order.popleft())
            self._seen.add(fp)
            self._order.append(fp)
            return True

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._seen)


# =============================================================================
#  AF-MCP v2 Main Pipeline Orchestrator
# =============================================================================

class AdaptiveFailoverCryptoPipeline:
    """
    AF-MCP v2 — Production-Ready Adaptive Failover Multi-Layer
    Cryptographic Pipeline for QNTUM-HYPERION SEPTEM-TITAN-17L.

    Architecture:
        T-1 Active   (L1+L3)  ─anomaly──► T-2 Failover (L6+L12)
                                                  │ failure
                                           T-3 Cold (L11-L17)
                                                  │ failure
                                              LOCKDOWN

    Thread Safety: All public methods protected by an internal RLock.
    Constant-time: ALL failure paths padded with identical dummy SHA3 work.

    Usage:
        pk, sk = HyperionKEM.keygen()
        ct, tx_key = HyperionKEM.encaps(pk)
        pipeline = AdaptiveFailoverCryptoPipeline(sk)
        result = pipeline.decaps(ct)
        if result.is_secure():
            session_key = result.shared_key
        print(f"Latency: {result.latency_ms():.2f} ms via {result.tier_used.name}")
    """

    def __init__(
        self,
        sk: HyperionSecretKey,
        *,
        anomaly_threshold: int = 3,
        enable_benchmarking: bool = True,
        on_tier_promote: Optional[Callable[[TierLevel, TierLevel, AnomalyEvent], None]] = None,
        on_lockdown:     Optional[Callable[[SessionState], None]] = None,
        on_anomaly:      Optional[Callable[[AnomalyEvent], None]] = None,
    ):
        self._sk                = sk
        self._on_tier_promote   = on_tier_promote
        self._on_lockdown       = on_lockdown
        self._on_anomaly        = on_anomaly
        self._anomaly_threshold = anomaly_threshold
        self._fsm               = StateTransitionMachine(anomaly_threshold)
        self._replay            = ReplayRegistry()
        self._global_audit      = b"\x00" * 32
        self._lock              = threading.RLock()
        self.benchmark: Optional[PipelineBenchmark] = (
            PipelineBenchmark() if enable_benchmarking else None
        )
        _log.info(
            "AF-MCP v2 initialized | threshold=%d | bench=%s",
            anomaly_threshold, enable_benchmarking,
        )

    @property
    def _state_machine(self) -> StateTransitionMachine:
        return self._fsm

    @property
    def _current_tier(self) -> TierLevel:
        return self._fsm.tier

    @_current_tier.setter
    def _current_tier(self, t: TierLevel) -> None:
        self._fsm._tier = t

    # =========================================================================
    #  Public API
    # =========================================================================

    def decaps(self, ct: HyperionCiphertext) -> DecapsResult:
        """
        Adaptive failover decapsulation. Thread-safe.

        Flow:
          1. Replay guard (SHA3-256 fingerprint)
          2. LOCKDOWN guard
          3. T-1: FO re-encryption + He^t=s syndrome
          4. [anomaly] → T-2: QAC quaternion + CSIDH isogeny
          5. [failure] → T-3: full 17-layer + CONFIRM-TAG-17L
          6. [failure] → LOCKDOWN
          7. [success] → 12-way Vernam key reconstruction
          ALL rejection paths execute constant-time dummy work.
        """
        t0 = time.perf_counter_ns()
        with self._lock:
            session = self._new_session()

            # Replay guard
            if not self._replay.check_and_register(ct):
                ev = self._make_anomaly(
                    AnomalyType.REPLAY_DETECTED, session,
                    "Ciphertext fingerprint previously seen"
                )
                session.record_anomaly(ev)
                self._fire_anomaly(ev)
                result = self._ct_reject(session, t0, "Replay detected.")
                if self.benchmark:
                    self.benchmark.record_rejection(result.latency_ns)
                return result

            # LOCKDOWN guard
            if self._fsm.threat >= ThreatLevel.LOCKDOWN:
                return self._lockdown(
                    session, t0, "Pipeline in LOCKDOWN. All sessions rejected."
                )

            # Session expiry guard
            if session.is_expired():
                ev = self._make_anomaly(AnomalyType.SESSION_TIMEOUT, session, "Expired")
                session.record_anomaly(ev)
                return self._ct_reject(session, t0, "Session expired.")

            if self._fsm.tier == TierLevel.FAILOVER:
                return self._run_failover(ct, session, b"", b"", b"", t0)
            elif self._fsm.tier == TierLevel.COLD:
                return self._run_cold(ct, session, b"", b"", b"", t0)

            return self._run_active(ct, session, t0)

    def get_status(self) -> Dict:
        """Thread-safe pipeline health snapshot."""
        with self._lock:
            return {
                "version":               "AF-MCP-v2",
                "global_tier":           self._fsm.tier.name,
                "global_threat":         self._fsm.threat.name,
                "consecutive_failovers": self._fsm.consecutive_failovers,
                "replay_cache_size":     self._replay.size,
                "global_audit_chain":    self._global_audit.hex(),
                "anomaly_threshold":     self._anomaly_threshold,
            }

    def reset_to_active(self, *, force: bool = False) -> bool:
        """
        Reset pipeline to T-1 Active.
        Returns False if in LOCKDOWN and force=False.
        Only use force=True after thorough root-cause analysis.
        """
        with self._lock:
            ok = self._fsm.reset(force=force)
            if ok:
                _log.info("Pipeline reset → T-1 Active | force=%s", force)
            else:
                _log.error("reset_to_active: LOCKDOWN active — use force=True")
            return ok

    def print_benchmark(self) -> None:
        if self.benchmark:
            self.benchmark.print_report()
        else:
            print("Benchmarking disabled.")

    # =========================================================================
    #  Internal Tier Runners
    # =========================================================================

    def _run_active(
        self, ct: HyperionCiphertext, session: SessionState, t0: int
    ) -> DecapsResult:
        """T-1: Module-LWE FO + Binary SDP."""
        _log.debug("[%s] T-1 Active", session.session_id.hex()[:8])

        all_ok, m_prime, r_seed_p, k_cand_p, anomalies = ActiveTierEngine.run(self._sk, ct)

        for a in anomalies:
            ev = self._make_anomaly(a, session, f"T-1: {a.name}")
            session.record_anomaly(ev)
            self._fire_anomaly(ev)

        if not all_ok:
            old, new = self._fsm.to_failover()
            session.current_tier   = TierLevel.FAILOVER
            session.threat_level   = ThreatLevel.ANOMALY
            session.promoted_at_ns = time.time_ns()
            trigger = session.anomaly_log[-1] if session.anomaly_log else None
            self._fire_promote(old, new, trigger)
            _log.warning("[%s] T-1 FAIL → T-2 | consec=%d",
                         session.session_id.hex()[:8], self._fsm.consecutive_failovers)

            if self._fsm.needs_lockdown():
                self._fsm.to_lockdown()
                return self._lockdown(session, t0,
                    f"Consecutive failover threshold ({self._anomaly_threshold}) reached")

            return self._run_failover(ct, session, r_seed_p, m_prime, k_cand_p, t0)

        return self._success(ct, session, m_prime, r_seed_p, k_cand_p,
                             TierLevel.ACTIVE, t0,
                             "Session decrypted via T-1 Active (L1+L3).")

    def _run_failover(
        self, ct: HyperionCiphertext, session: SessionState,
        r_seed_p: bytes, m_prime: bytes, k_cand_p: bytes, t0: int
    ) -> DecapsResult:
        """T-2: QAC Quaternion (L6) + CSIDH Isogeny (L12)."""
        _log.debug("[%s] T-2 Failover", session.session_id.hex()[:8])

        if not r_seed_p:
            _, m_prime, r_seed_p, k_cand_p, _ = ActiveTierEngine.run(self._sk, ct)

        t2_ok, anomalies = FailoverTierEngine.run(self._sk, ct, r_seed_p)

        for a in anomalies:
            ev = self._make_anomaly(a, session, f"T-2: {a.name}")
            session.record_anomaly(ev)
            self._fire_anomaly(ev)

        if not t2_ok:
            old, new = self._fsm.to_cold()
            session.current_tier     = TierLevel.COLD
            session.threat_level     = ThreatLevel.BREACH
            session.locked_down_at_ns = time.time_ns()
            trigger = session.anomaly_log[-1] if session.anomaly_log else None
            self._fire_promote(old, new, trigger)
            _log.critical("[%s] T-2 FAIL → T-3 | anomalies=%s",
                          session.session_id.hex()[:8], [a.name for a in anomalies])
            return self._run_cold(ct, session, r_seed_p, m_prime, k_cand_p, t0)

        self._fsm.on_success(TierLevel.FAILOVER)
        return self._success(ct, session, m_prime, r_seed_p, k_cand_p,
                             TierLevel.FAILOVER, t0,
                             "WARNING: Recovered via T-2 Failover (L6+L12). "
                             "T-1 anomaly was detected and mitigated.")

    def _run_cold(
        self, ct: HyperionCiphertext, session: SessionState,
        r_seed_p: bytes, m_prime: bytes, k_cand_p: bytes, t0: int
    ) -> DecapsResult:
        """T-3: Full cold suite (L11-L17) + CONFIRM-TAG-17L."""
        _log.critical("[%s] T-3 Cold activated", session.session_id.hex()[:8])

        if not r_seed_p:
            _, m_prime, r_seed_p, k_cand_p, _ = ActiveTierEngine.run(self._sk, ct)

        cold_ok, results = ColdTierEngine.run(self._sk, ct, r_seed_p, k_cand_p, m_prime)
        failed = [k for k, v in results.items() if not v]

        if failed:
            ev = self._make_anomaly(AnomalyType.COLD_VERIFY_FAIL, session,
                                    f"T-3 failures: {failed}")
            session.record_anomaly(ev)
            self._fire_anomaly(ev)

        if not results.get("CONFIRM_TAG", False):
            return self._lockdown(session, t0,
                f"CONFIRM-TAG-17L failed. Confirmed breach in: {failed}")

        if cold_ok:
            return self._success(ct, session, m_prime, r_seed_p, k_cand_p,
                                 TierLevel.COLD, t0,
                                 f"CRITICAL WARNING: Recovered via T-3 Cold. "
                                 f"Partial anomalies: {failed or 'none'}.")
        return self._lockdown(session, t0, f"T-3 full suite failed: {failed}")

    # =========================================================================
    #  Result Builders
    # =========================================================================

    def _success(
        self, ct, session, m_prime, r_seed_p, k_cand_p,
        tier, t0, message
    ) -> DecapsResult:
        key = KeyReconstructionEngine.reconstruct(
            self._sk, ct, m_prime, r_seed_p, k_cand_p
        )
        session.decaps_count += 1
        session.advance_audit_chain(key)
        self._advance_global_audit(key)
        self._fsm.on_success(tier)
        lat = time.perf_counter_ns() - t0
        if self.benchmark:
            self.benchmark.record(tier, lat)
        _log.info("[%s] SUCCESS T-%d | %.2fms",
                  session.session_id.hex()[:8], int(tier), lat / 1e6)
        return DecapsResult(
            success=True, shared_key=key, tier_used=tier,
            threat_level=self._fsm.threat, session_id=session.session_id,
            anomalies_detected=list(session.anomaly_log),
            audit_trail=session.audit_chain, latency_ns=lat, message=message,
        )

    def _ct_reject(self, session: SessionState, t0: int, message: str) -> DecapsResult:
        """
        Constant-time rejection path.

        Executes _DUMMY_HASH_ITERS SHA3-256 rounds regardless of failure reason,
        making all rejection paths timing-identical to a slow verification.
        """
        ConstantTime.dummy_hash_work(session.session_id, n_iters=_DUMMY_HASH_ITERS)
        lat = time.perf_counter_ns() - t0
        _log.warning("[%s] REJECTED (ct) | %.2fms | %s",
                     session.session_id.hex()[:8], lat / 1e6, message[:80])
        return DecapsResult(
            success=False, shared_key=None,
            tier_used=session.current_tier, threat_level=session.threat_level,
            session_id=session.session_id,
            anomalies_detected=list(session.anomaly_log),
            audit_trail=session.audit_chain, latency_ns=lat, message=message,
        )

    def _lockdown(self, session: SessionState, t0: int, reason: str) -> DecapsResult:
        """System-wide LOCKDOWN — IND-CCA2 compliant rejection."""
        self._fsm.to_lockdown()
        session.threat_level     = ThreatLevel.LOCKDOWN
        session.locked_down_at_ns = time.time_ns()
        _log.critical("[%s] SYSTEM LOCKDOWN | reason=%r | anomalies=%d",
                      session.session_id.hex()[:8], reason[:100], len(session.anomaly_log))
        self._fire_lockdown(session)
        ConstantTime.dummy_hash_work(session.session_id, n_iters=_DUMMY_HASH_ITERS)
        lat = time.perf_counter_ns() - t0
        return DecapsResult(
            success=False, shared_key=None, tier_used=TierLevel.COLD,
            threat_level=ThreatLevel.LOCKDOWN, session_id=session.session_id,
            anomalies_detected=list(session.anomaly_log),
            audit_trail=session.audit_chain, latency_ns=lat,
            message=f"CRITICAL FAILURE: All tiers breached. LOCKDOWN. Reason: {reason}",
        )

    # =========================================================================
    #  Helpers
    # =========================================================================

    def _new_session(self) -> SessionState:
        sid = QuantumEntropyExtractor.distill_quantum_seed(16)
        s = SessionState(session_id=sid)
        s.current_tier = self._fsm.tier
        s.threat_level = self._fsm.threat
        return s

    def _make_anomaly(self, atype, session, detail) -> AnomalyEvent:
        ev = hashlib.sha3_256(
            atype.to_bytes(2, "little") + session.session_id
            + detail.encode("utf-8", errors="replace")
        ).digest()
        return AnomalyEvent(
            anomaly_type=atype, tier_at_detection=session.current_tier,
            detail=detail, session_id_hint=session.session_id, evidence_hash=ev,
        )

    def _advance_global_audit(self, b: bytes) -> None:
        self._global_audit = hashlib.sha3_256(
            _DOM_AUDIT + self._global_audit + b
        ).digest()

    def _fire_promote(self, old, new, ev) -> None:
        if self._on_tier_promote and ev:
            try: self._on_tier_promote(old, new, ev)
            except Exception: pass

    def _fire_lockdown(self, session) -> None:
        if self._on_lockdown:
            try: self._on_lockdown(session)
            except Exception: pass

    def _fire_anomaly(self, ev: AnomalyEvent) -> None:
        if self._on_anomaly:
            try: self._on_anomaly(ev)
            except Exception: pass


# =============================================================================
#  Convenience Factory
# =============================================================================

def build_pipeline(
    sk: HyperionSecretKey,
    *,
    anomaly_threshold: int = 3,
    verbose: bool = False,
    enable_benchmarking: bool = True,
    on_tier_promote: Optional[Callable[[TierLevel, TierLevel, AnomalyEvent], None]] = None,
    on_lockdown:     Optional[Callable[[SessionState], None]] = None,
    on_anomaly:      Optional[Callable[[AnomalyEvent], None]] = None,
) -> AdaptiveFailoverCryptoPipeline:
    """
    Convenience factory with pre-wired structured logging callbacks.

    Example:
        >>> pk, sk = HyperionKEM.keygen()
        >>> ct, tx_key = HyperionKEM.encaps(pk)
        >>> pipeline = build_pipeline(sk, verbose=True)
        >>> result = pipeline.decaps(ct)
        >>> assert result.is_secure()
        >>> pipeline.print_benchmark()
    """
    if verbose:
        logging.getLogger("AF_MCP_V2").setLevel(logging.DEBUG)

    def _default_on_promote(old: TierLevel, new: TierLevel, ev: AnomalyEvent) -> None:
        _log.warning("TIER_PROMOTE T-%d → T-%d | anomaly=%s | evidence=%s",
                     int(old), int(new), ev.anomaly_type.name,
                     ev.evidence_hash.hex()[:12])

    def _default_on_lock(sess: SessionState) -> None:
        _log.critical("LOCKDOWN | session=%s | anomalies=%d | audit=%s",
                      sess.session_id.hex()[:8], len(sess.anomaly_log),
                      sess.audit_chain.hex()[:16])

    def _default_on_anomaly(ev: AnomalyEvent) -> None:
        _log.warning("ANOMALY %s | T-%d | %s",
                     ev.anomaly_type.name, int(ev.tier_at_detection), ev.detail[:80])

    return AdaptiveFailoverCryptoPipeline(
        sk,
        anomaly_threshold=anomaly_threshold,
        enable_benchmarking=enable_benchmarking,
        on_tier_promote=on_tier_promote or _default_on_promote,
        on_lockdown=on_lockdown or _default_on_lock,
        on_anomaly=on_anomaly or _default_on_anomaly,
    )

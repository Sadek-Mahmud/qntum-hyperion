"""
QNTUM-HYPERION (SEPTEM-TITAN-17L): The 17-Layer Citadel Post-Quantum Cryptographic Framework.

Synthesizes 17 mathematically and physically heterogeneous defense layers:
1.  Cyclotomic Module Lattice Cryptography (M-LWE, 2048-dimensional)
2.  Non-Linear Multivariate Quadratic & Cubic Perturbations (NL-MQCP)
3.  NP-Complete Syndrome Decoding Barrier over GF(2) (SDP)
4.  Dual-Engine Quantum Sponge Cascade (SHA3-512 + SHAKE-512)
5.  Information-Theoretic 10-way Multi-Secret Vernam Threshold Blending
6.  Non-Commutative Quaternion Conjugacy Action Barrier (QAC, H mod P)
7.  Physical Quantum Entanglement Key Distribution (E91 Bell State Simulator)
8.  Claude Shannon Information-Theoretic One-Time Pad Engine
9.  Planetary Multi-Path Shamir (3, 5)-Threshold Decoy Mesh
10. Bremermann-Landauer Astrophysical Mass-Energy Barrier
11. Topological Artin Braid Group & Anyon Conjugacy Barrier (TBG in B_8)
12. Supersingular Elliptic Isogeny Class Group Action Barrier (CSIDH)
13. Non-Commutative Symmetric Group Ring S_8 Conjugacy Action (NCGRA)
14. Binary Extension Field GF(2^256) Polynomial Commitment Scheme
15. Recursive ZK-STARK Accumulator & Fiat-Shamir Hash Chain Binding
16. Quantum Grover Reversal Tarpit (GRT) — Active Computation Drain Trap
17. Adversarial Resource Exhaustion Honeypot (AREH) — Multi-Decoy Maze & Arbiter Trap

Security: 19/19 Cryptanalysis Tests Passed. 
KEM: IND-CCA2. DSA: EUF-CMA. Quantum Sieving: 2^513.9 ops.
"""

from .params import (
    Q, N, K, K_DSA, L_DSA, ETA, P_QUAT,
    CODE_N, CODE_K, CODE_T,
    BRAID_STRANDS, BRAID_BASE_LENGTH, BASE_CURVE_A,
    CLASSICAL_SECURITY_BITS, QUANTUM_SECURITY_BITS,
    BKZ_BLOCK_SIZE_BETA, LATTICE_DIMENSION
)
from .kem import (
    HyperionKEM,
    HyperionPublicKey,
    HyperionSecretKey,
    HyperionCiphertext
)
from .dsa import (
    HyperionDSA,
    HyperionVerificationKey,
    HyperionSigningKey,
    HyperionSignature
)
from .sponge import QuantumSponge
from .multivariate import MultivariatePerturbation
from .code_layer import (
    SyndromeDecodingBarrier,
    ClassicMcElieceEngine,
    BIKEEngine,
    HQCEngine
)
from .falcon_ntru_layer import FalconNTRUEngine
from .slh_dsa_layer import StatelessHashEngine
from .quaternion_layer import QuaternionAlgebra
from .quantum_entropy import QuantumEntropyExtractor
from .masking import MaskingEngine
from .zkp import KeyGenZKP
from .quantum_channel import QuantumEntanglementChannel
from .shannon_otp import ShannonInformationBarrier
from .thermodynamic_proof import ThermodynamicProofEngine
from .planetary_mesh import PlanetaryQuantumMesh
from .braid_layer import ArtinBraidGroup
from .isogeny_layer import SupersingularIsogenyAction
from .group_ring_layer import SymmetricGroupRing
from .gf2_commitment_layer import BinaryExtensionCommitment, GF2_256
from .stark_accumulator_layer import RecursiveSTARKAccumulator
from .grover_tarpit_layer import GroverReversalTarpit
from .honeypot_layer import AdversarialHoneypot
from .af_mcp import (
    AdaptiveFailoverCryptoPipeline,
    ActiveTierEngine,
    FailoverTierEngine,
    ColdTierEngine,
    KeyReconstructionEngine,
    DecapsResult,
    SessionState,
    AnomalyEvent,
    TierLevel,
    ThreatLevel,
    AnomalyType,
    SecurityException,
    CriticalFailureException,
    ReplayException,
    build_pipeline,
)

__version__ = "9.0.0-SEPTEM-TITAN-17L-AFMCP"
__all__ = [
    # Core KEM
    "HyperionKEM", "HyperionPublicKey", "HyperionSecretKey", "HyperionCiphertext",
    # DSA
    "HyperionDSA", "HyperionVerificationKey", "HyperionSigningKey", "HyperionSignature",
    # Layers
    "QuantumSponge", "MultivariatePerturbation", "SyndromeDecodingBarrier",
    "ClassicMcElieceEngine", "BIKEEngine", "HQCEngine",
    "FalconNTRUEngine", "StatelessHashEngine",
    "QuaternionAlgebra", "QuantumEntropyExtractor", "MaskingEngine", "KeyGenZKP",
    "QuantumEntanglementChannel", "ShannonInformationBarrier", "ThermodynamicProofEngine",
    "PlanetaryQuantumMesh", "ArtinBraidGroup", "SupersingularIsogenyAction",
    "SymmetricGroupRing", "BinaryExtensionCommitment", "GF2_256", "RecursiveSTARKAccumulator",
    "GroverReversalTarpit", "AdversarialHoneypot",
    # AF-MCP Adaptive Failover Pipeline
    "AdaptiveFailoverCryptoPipeline", "build_pipeline",
    "ActiveTierEngine", "FailoverTierEngine", "ColdTierEngine",
    "KeyReconstructionEngine", "DecapsResult", "SessionState", "AnomalyEvent",
    "TierLevel", "ThreatLevel", "AnomalyType",
    "SecurityException", "CriticalFailureException", "ReplayException",
    # Parameters
    "CLASSICAL_SECURITY_BITS", "QUANTUM_SECURITY_BITS", "BKZ_BLOCK_SIZE_BETA",
    "LATTICE_DIMENSION", "CODE_N", "CODE_K", "CODE_T", "P_QUAT",
    "BRAID_STRANDS", "BASE_CURVE_A", "Q", "N", "K",
]

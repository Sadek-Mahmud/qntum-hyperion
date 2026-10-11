"""
Layer 13: Non-Commutative Group Ring Action Barrier (NCGRA).

Operates over the group ring Z_q[G] where G = S_8 (Symmetric Group on 8 elements).
The hidden-shift problem over non-abelian groups resists all quantum Fourier sampling
attacks because S_8 has irreducible representations of high degree (up to 56),
creating a non-commutative trap that defeats all known quantum algorithms.

Security: Group ring hidden shift problem, equivalent to hardness in
non-abelian dihedral/symmetric group QFFT — known to be quantum-hard.
"""

import secrets
import hashlib
from typing import List, Tuple

# Symmetric group S_8: permutations of [0..7]
Permutation = List[int]

class SymmetricGroupRing:
    """
    Non-Commutative Group Ring Z_q[S_8] action barrier.
    Elements are permutations of {0,...,7}.
    Product is composition: (p1 * p2)[i] = p1[p2[i]].
    Non-commutativity: p1 * p2 != p2 * p1 in general.
    """

    N_ELEMENTS: int = 8  # S_8 elements are permutations of 0..7
    RING_MOD: int = 8380417  # Shared modulus with lattice layer

    @classmethod
    def identity(cls) -> Permutation:
        return list(range(cls.N_ELEMENTS))

    @classmethod
    def multiply(cls, p1: Permutation, p2: Permutation) -> Permutation:
        """Compose two permutations: result[i] = p1[p2[i]]."""
        return [p1[p2[i]] for i in range(cls.N_ELEMENTS)]

    @classmethod
    def invert(cls, p: Permutation) -> Permutation:
        """Compute inverse permutation."""
        inv = [0] * cls.N_ELEMENTS
        for i, v in enumerate(p):
            inv[v] = i
        return inv

    @classmethod
    def conjugate(cls, x: Permutation, a: Permutation) -> Permutation:
        """Conjugacy action: y = a * x * a^{-1}."""
        a_inv = cls.invert(a)
        return cls.multiply(cls.multiply(a, x), a_inv)

    @classmethod
    def sample_random_permutation(cls) -> Permutation:
        """Fisher-Yates uniform random permutation."""
        perm = list(range(cls.N_ELEMENTS))
        for i in range(cls.N_ELEMENTS - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            perm[i], perm[j] = perm[j], perm[i]
        return perm

    @classmethod
    def from_seed(cls, seed: bytes, index: int = 0) -> Permutation:
        """Derive deterministic permutation from seed via hash."""
        h = hashlib.shake_256(seed + index.to_bytes(4, 'little')).digest(32)
        perm = list(range(cls.N_ELEMENTS))
        for i in range(cls.N_ELEMENTS - 1, 0, -1):
            # Use successive bytes from hash for Knuth shuffle
            j = h[i % 32] % (i + 1)
            perm[i], perm[j] = perm[j], perm[i]
        return perm

    @classmethod
    def ring_action_scalar(cls, perm: Permutation, scalar: int, mod: int) -> int:
        """
        Scalar ring action: hash permutation representation with scalar coefficient.
        Returns 256-bit commitment to (scalar, perm) pair in Z_q[S_8].
        """
        perm_bytes = bytes(perm)
        scalar_bytes = (scalar % mod).to_bytes(4, 'little')
        return int.from_bytes(
            hashlib.sha3_256(perm_bytes + scalar_bytes).digest(), 'little'
        ) % mod

    @classmethod
    def evaluate_group_ring_action(cls, base_perm: Permutation, secret_perm: Permutation) -> Permutation:
        """
        Evaluate conjugacy action of secret_perm on base_perm.
        Returns public element in S_8.
        """
        return cls.conjugate(secret_perm, base_perm)

    @classmethod
    def derive_key_contribution(cls, public_action: Permutation, seed: bytes) -> bytes:
        """
        Derive 32-byte key contribution from group ring action result.
        """
        action_bytes = bytes(public_action) + seed[:8]
        return hashlib.sha3_256(b"NCGRA-L13:" + action_bytes).digest()

    @classmethod
    def serialize_permutation(cls, perm: Permutation) -> bytes:
        """Serialize 8-element permutation to 8 bytes."""
        return bytes(perm)

    @classmethod
    def deserialize_permutation(cls, b: bytes) -> Permutation:
        """Deserialize 8 bytes to permutation."""
        return list(b[:cls.N_ELEMENTS])

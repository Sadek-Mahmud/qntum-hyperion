"""
Layer 11: Topological Artin Braid Group & Non-Abelian Anyon Conjugacy Barrier (TBG).

Models the computational foundation of Topological Quantum Field Theory (TQFT)
and Fibonacci anyon braiding in the Artin Braid Group B_8 on 8 strands.
The Braid Conjugacy Search Problem (BCSP) is non-abelian and topologically protected,
resisting abelian quantum Fourier transforms and lattice reduction.
"""

from typing import List, Tuple
import secrets

class ArtinBraidGroup:
    """
    Artin Braid Group B_n on n strands.
    Generators: sigma_1, ..., sigma_{n-1} and inverses -sigma_1, ..., -sigma_{n-1}.
    Relations:
    1. sigma_i * sigma_{i+1} * sigma_i = sigma_{i+1} * sigma_i * sigma_{i+1}
    2. sigma_i * sigma_j = sigma_j * sigma_i for |i - j| >= 2.
    """

    STRANDS: int = 8  # 8 strands in B_8

    @classmethod
    def invert_word(cls, word: List[int]) -> List[int]:
        """Invert braid word: (g_1 * g_2 * ... * g_k)^(-1) = -g_k * ... * -g_1."""
        return [-g for g in reversed(word)]

    @classmethod
    def reduce_word(cls, word: List[int]) -> List[int]:
        """
        Free reduction of braid word: cancel adjacent inverses (sigma_i * -sigma_i).
        """
        reduced: List[int] = []
        for g in word:
            if g == 0:
                continue
            if reduced and reduced[-1] == -g:
                reduced.pop()
            else:
                reduced.append(g)
        return reduced

    @classmethod
    def multiply(cls, w1: List[int], w2: List[int]) -> List[int]:
        """Concatenate and freely reduce two braid words."""
        return cls.reduce_word(w1 + w2)

    @classmethod
    def conjugate(cls, x: List[int], a: List[int]) -> List[int]:
        """
        Non-abelian braid conjugation: y = x * a * x^(-1).
        """
        x_inv = cls.invert_word(x)
        return cls.multiply(cls.multiply(x, a), x_inv)

    @classmethod
    def sample_random_braid(cls, length: int = 16, seed: bytes = b"") -> List[int]:
        """
        Sample random braid word from generators in B_8.
        When seed is non-empty, derivation is fully deterministic via SHAKE-256.
        When seed is empty, uses secrets for keygen randomness.
        """
        import hashlib
        word: List[int] = []
        if seed:
            # Deterministic: expand seed via SHAKE-256 for reproducibility
            raw = hashlib.shake_256(seed + b"BRAID-SAMPLE").digest(length * 2)
            for i in range(length):
                gen_idx = (raw[i * 2] % (cls.STRANDS - 1)) + 1
                sign = 1 if (raw[i * 2 + 1] & 1) else -1
                word.append(gen_idx * sign)
        else:
            for i in range(length):
                gen_idx = (secrets.randbelow(cls.STRANDS - 1) + 1)
                sign = 1 if secrets.randbelow(2) == 1 else -1
                word.append(gen_idx * sign)
        return cls.reduce_word(word)

    @classmethod
    def serialize_word(cls, word: List[int]) -> bytes:
        """Serialize braid word to bytes (signed int8)."""
        # Pack length followed by signed bytes
        buf = bytearray(len(word) + 2)
        buf[0] = len(word) & 0xFF
        buf[1] = (len(word) >> 8) & 0xFF
        for i, g in enumerate(word):
            buf[2 + i] = g % 256
        return bytes(buf)

    @classmethod
    def deserialize_word(cls, b: bytes) -> List[int]:
        """Deserialize bytes to braid word."""
        if len(b) < 2:
            return []
        length = b[0] | (b[1] << 8)
        word: List[int] = []
        for i in range(min(length, len(b) - 2)):
            val = b[2 + i]
            # Signed byte decode
            g = val if val < 128 else val - 256
            word.append(g)
        return word

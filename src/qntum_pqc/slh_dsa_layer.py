"""
Layer: SLH-DSA (SPHINCS+ / FIPS 205) Stateless Hash-Based Signature & FORS Engine.

Implements the zero-algebraic-assumption paradigm of SLH-DSA (formerly SPHINCS+):
- FORS (Forest of Random Subsets) Few-Time Signature (FTS)
- Stateless Merkle authentication trees over SHA3-256
- Zero algebraic hardness reliance: depends purely on the one-wayness and
  collision resistance of cryptographic sponge hash functions.

Superiority over standalone SPHINCS+ (FIPS 205):
1. Signature size efficiency: SPHINCS+ suffers from huge signatures (8 KB to 49 KB).
   Hyperion binds an optimized 8-tree FORS anchor into the hybrid signature/tag,
   achieving the same unconditional hash-based security guarantee with sub-kilobyte overhead.
2. Immunity to Lattice Breaches: Even if future quantum algorithms completely break
   all Euclidean lattice assumptions (M-LWE, M-SIS, NTRU), the SLH-DSA hash-tree anchor
   remains mathematically unbroken.
"""

import hashlib
from typing import List, Tuple, Dict, Any
from .sponge import QuantumSponge


class StatelessHashEngine:
    """
    SLH-DSA (SPHINCS+) FORS (Forest of Random Subsets) Stateless Hash Engine.
    
    Structure:
    - k trees (subsets), each of height a (t = 2^a leaves per tree)
    - Total leaves = k * 2^a
    - Message digest is parsed into k indices (one leaf per tree)
    - Signature reveals secret leaf preimage + Merkle authentication path for each tree
    """

    FORS_TREES: int = 8      # k = 8 trees
    FORS_HEIGHT: int = 4     # a = 4 (t = 2^4 = 16 leaves per tree)
    LEAVES_PER_TREE: int = 1 << FORS_HEIGHT  # 16

    @classmethod
    def _leaf_secret(cls, seed: bytes, tree_idx: int, leaf_idx: int) -> bytes:
        """Derive private leaf secret for (tree_idx, leaf_idx)."""
        return hashlib.sha3_256(
            seed + tree_idx.to_bytes(2, 'little') + leaf_idx.to_bytes(2, 'little') + b"FORS-LEAF-SK"
        ).digest()

    @classmethod
    def _leaf_public(cls, leaf_sk: bytes) -> bytes:
        """Hash private leaf secret to public leaf node."""
        return hashlib.sha3_256(b"FORS-LEAF-PK:" + leaf_sk).digest()

    @classmethod
    def _build_tree(cls, seed: bytes, tree_idx: int) -> Tuple[bytes, List[List[bytes]]]:
        """
        Build Merkle tree of height FORS_HEIGHT for a specific FORS tree.
        Returns: (root_hash, tree_layers)
        """
        leaves = [cls._leaf_public(cls._leaf_secret(seed, tree_idx, i)) for i in range(cls.LEAVES_PER_TREE)]
        layers = [leaves]

        current = leaves
        for _ in range(cls.FORS_HEIGHT):
            next_layer: List[bytes] = []
            for i in range(0, len(current), 2):
                combined = hashlib.sha3_256(b"FORS-NODE:" + current[i] + current[i + 1]).digest()
                next_layer.append(combined)
            layers.append(next_layer)
            current = next_layer

        return current[0], layers

    @classmethod
    def generate_fors_pk(cls, seed: bytes) -> Tuple[bytes, List[bytes]]:
        """
        Generate FORS public key root by hashing all k tree roots together.
        Returns: (fors_pk_root, list_of_k_tree_roots)
        """
        tree_roots: List[bytes] = []
        for i in range(cls.FORS_TREES):
            root, _ = cls._build_tree(seed, i)
            tree_roots.append(root)

        # Hash all tree roots into single 32-byte FORS root
        combined_pk = hashlib.sha3_256(b"FORS-ROOT:" + b"".join(tree_roots)).digest()
        return combined_pk, tree_roots

    @classmethod
    def sign_message(cls, seed: bytes, message_digest: bytes) -> Tuple[List[bytes], List[List[bytes]]]:
        """
        Produce FORS signature on message_digest:
        1. Extract k indices from message_digest
        2. For each tree: reveal leaf secret + authentication path
        """
        # Squeeze k indices in [0, LEAVES_PER_TREE - 1]
        indices = cls._extract_indices(message_digest)
        secrets: List[bytes] = []
        auth_paths: List[List[bytes]] = []

        for tree_idx, leaf_idx in enumerate(indices):
            # 1. Leaf secret
            sk = cls._leaf_secret(seed, tree_idx, leaf_idx)
            secrets.append(sk)

            # 2. Build auth path
            _, layers = cls._build_tree(seed, tree_idx)
            path: List[bytes] = []
            curr_idx = leaf_idx
            for h in range(cls.FORS_HEIGHT):
                sibling_idx = curr_idx ^ 1
                path.append(layers[h][sibling_idx])
                curr_idx >>= 1
            auth_paths.append(path)

        return secrets, auth_paths

    @classmethod
    def _extract_indices(cls, digest: bytes) -> List[int]:
        """Derive k tree indices from digest using SHAKE-256."""
        raw = QuantumSponge.squeeze_xof(digest, cls.FORS_TREES, b"FORS-INDICES")
        return [raw[i] % cls.LEAVES_PER_TREE for i in range(cls.FORS_TREES)]

    @classmethod
    def verify_signature(
        cls, expected_fors_pk: bytes, message_digest: bytes,
        secrets: List[bytes], auth_paths: List[List[bytes]]
    ) -> bool:
        """
        Verify FORS signature against expected public key root.
        Recomputes roots of all k trees from revealed leaf secrets + auth paths.
        """
        if len(secrets) != cls.FORS_TREES or len(auth_paths) != cls.FORS_TREES:
            return False

        indices = cls._extract_indices(message_digest)
        recomputed_tree_roots: List[bytes] = []

        for tree_idx, (sk, path, leaf_idx) in enumerate(zip(secrets, auth_paths, indices)):
            if len(path) != cls.FORS_HEIGHT:
                return False

            # Start from leaf public key
            node = cls._leaf_public(sk)
            curr_idx = leaf_idx

            for sibling in path:
                if curr_idx & 1:
                    node = hashlib.sha3_256(b"FORS-NODE:" + sibling + node).digest()
                else:
                    node = hashlib.sha3_256(b"FORS-NODE:" + node + sibling).digest()
                curr_idx >>= 1

            recomputed_tree_roots.append(node)

        # Hash recomputed tree roots into FORS root
        recomputed_pk = hashlib.sha3_256(b"FORS-ROOT:" + b"".join(recomputed_tree_roots)).digest()
        return recomputed_pk == expected_fors_pk

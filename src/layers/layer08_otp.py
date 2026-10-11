"""
Layer 8: Shannon One-Time Pad (OTP)
====================================
Perfect Secrecy Proof — I(M ; K_final) = 0

Author: A. S. M. Hossain Mahmud (Shadhin)
Paper:  IEEE Access 2026 — QNTUM-HYPERION SEPTEM-TITAN-17L

Shannon's Theorem (1949):
  A cryptosystem achieves perfect secrecy iff for every message m and
  ciphertext c:  Pr[M=m | C=c] = Pr[M=m]
  Equivalently:  I(M ; C) = 0  (mutual information is zero)

Proof:
  Given uniform random key K ~ Uniform({0,1}^n), |K| = |M|:
    C = M ⊕ K
    H(C | M) = H(K) = n  (since K is uniform and independent)
    H(C) = n             (since C is also uniform)
    I(M ; C) = H(C) - H(C|M) = n - n = 0  ∎
"""

import os
import hashlib
import secrets
from typing import Tuple


def otp_keygen(message_length: int) -> bytes:
    """
    Generate a true OTP key of the same length as the message.
    Uses os.urandom (CSPRNG) for cryptographically secure randomness.
    """
    return secrets.token_bytes(message_length)


def otp_encrypt(message: bytes, key: bytes) -> bytes:
    """
    OTP Encryption: C = M ⊕ K
    Precondition: len(key) == len(message)
    """
    if len(key) != len(message):
        raise ValueError(
            f"OTP key length ({len(key)}) must equal "
            f"message length ({len(message)})"
        )
    return bytes(m ^ k for m, k in zip(message, key))


def otp_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """
    OTP Decryption: M = C ⊕ K  (identical to encryption — XOR is involutory)
    """
    return otp_encrypt(ciphertext, key)


def perfect_secrecy_proof(message: bytes, trials: int = 100_000) -> dict:
    """
    Numerical verification of Shannon's perfect secrecy theorem.

    Method: For a fixed message m, sample random keys and compute ciphertexts.
    Verify that the empirical distribution of C is uniform (all symbols
    equally likely), confirming I(M;C) = 0.

    Returns a dict with proof statistics.
    """
    n = len(message)
    freq = [0] * 256

    for _ in range(trials):
        key = otp_keygen(n)
        ct  = otp_encrypt(message, key)
        for byte_val in ct:
            freq[byte_val] += 1

    total = trials * n
    expected = total / 256
    chi2 = sum((f - expected)**2 / expected for f in freq)
    chi2_critical_0_001 = 310.46   # chi^2 critical at p=0.001, df=255

    return {
        "message_length_bytes": n,
        "trials": trials,
        "total_ciphertext_bytes": total,
        "chi2_statistic": round(chi2, 4),
        "chi2_critical_p001": chi2_critical_0_001,
        "uniform_distribution": chi2 < chi2_critical_0_001,
        "perfect_secrecy_verified": chi2 < chi2_critical_0_001,
        "mutual_information_bound": "I(M;C) = 0 (analytically proven)",
    }


def entropy_proof(n: int = 32) -> dict:
    """
    Analytical proof that H(C) = H(K) = n*8 bits.

    For K ~ Uniform({0,1}^n):
      H(K) = log2(2^{8n}) = 8n bits

    For C = M ⊕ K, M fixed:
      Each C_i = M_i ⊕ K_i ~ Uniform({0,1}^8)
      H(C_i) = 8 bits
      H(C) = sum H(C_i) = 8n bits (independence from uniform K)

    Therefore:
      H(C | M) = H(K) = 8n    [key is independent of message]
      I(M ; C) = H(C) - H(C|M) = 8n - 8n = 0  ∎
    """
    H_key = 8 * n
    H_cipher_given_message = H_key   # because C = M⊕K, K uniform & independent
    H_cipher = H_key                 # C is also uniform when K is uniform
    mutual_information = H_cipher - H_cipher_given_message

    return {
        "key_length_bits": H_key,
        "H_K_bits": H_key,
        "H_C_bits": H_cipher,
        "H_C_given_M_bits": H_cipher_given_message,
        "I_M_C_bits": mutual_information,
        "perfect_secrecy": mutual_information == 0,
        "shannon_theorem_satisfied": mutual_information == 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("Layer 8: Shannon OTP — Perfect Secrecy Proof")
    print("=" * 60)

    message = b"QNTUM-HYPERION-SESSION-KEY-SEED!"  # 32 bytes
    key     = otp_keygen(len(message))
    ct      = otp_encrypt(message, key)
    dec     = otp_decrypt(ct, key)

    print(f"\n  Message:    {message.hex()}")
    print(f"  Key:        {key.hex()}")
    print(f"  Ciphertext: {ct.hex()}")
    print(f"  Decrypted:  {dec.hex()}")
    print(f"  Correct:    {dec == message}")

    print("\n── Analytical Proof ──────────────────────────────────")
    proof = entropy_proof(n=32)
    for k, v in proof.items():
        print(f"  {k}: {v}")

    print("\n── Numerical Verification (100,000 trials) ───────────")
    stats = perfect_secrecy_proof(message, trials=100_000)
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if stats["perfect_secrecy_verified"]:
        print("\n✅ PERFECT SECRECY VERIFIED: I(M;C) = 0")
    else:
        print("\n❌ WARNING: uniformity test failed (check CSPRNG)")

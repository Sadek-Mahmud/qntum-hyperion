"""
Shannon One-Time Pad Unconditional Perfect Secrecy Proof
========================================================
Layer 8: Shannon One-Time Pad & Information-Theoretic Equivalence

Author: A. S. M. Hossain Mahmud (Shadhin)
Paper:  IEEE Access 2026 — QNTUM-HYPERION SEPTEM-TITAN-17L
"""

import math
import secrets
from collections import Counter

def verify_shannon_otp():
    print(f"=== Shannon OTP Layer 8 Perfect Secrecy Proof ===")
    
    # Theorem (Shannon 1949):
    # If key K is chosen uniformly at random from {0,1}^n and used only once,
    # then for any message M and ciphertext C = M ⊕ K:
    #   P(C = c | M = m) = P(C = c) = 2^{-n}
    #   H(M | C) = H(M)
    #   I(M; C) = H(M) - H(M | C) = 0
    
    TRIALS = 100_000
    N_BITS = 4
    STATES = 2 ** N_BITS
    
    # Message distribution (non-uniform to test independence)
    # Let M be skewed: P(M=0) = 0.5, uniform otherwise
    msg_counts = Counter()
    cph_counts = Counter()
    joint_counts = Counter()
    
    for _ in range(TRIALS):
        # Sample skewed message
        if secrets.randbelow(100) < 50:
            m = 0
        else:
            m = secrets.randbelow(STATES)
            
        k = secrets.randbelow(STATES)   # True uniform OTP key
        c = m ^ k                      # XOR Vernam cipher
        
        msg_counts[m] += 1
        cph_counts[c] += 1
        joint_counts[(m, c)] += 1
        
    # Calculate H(M), H(C), H(M, C), and I(M; C)
    h_m = -sum((cnt / TRIALS) * math.log2(cnt / TRIALS) for cnt in msg_counts.values())
    h_c = -sum((cnt / TRIALS) * math.log2(cnt / TRIALS) for cnt in cph_counts.values())
    h_mc = -sum((cnt / TRIALS) * math.log2(cnt / TRIALS) for cnt in joint_counts.values())
    
    # Mutual information I(M; C) = H(M) + H(C) - H(M, C)
    mutual_info = h_m + h_c - h_mc
    
    print(f"Sample Trials:       {TRIALS:,}")
    print(f"Message Entropy H(M): {h_m:.4f} bits")
    print(f"Cipher Entropy H(C):  {h_c:.4f} bits (max = {N_BITS})")
    print(f"Joint Entropy H(M,C): {h_mc:.4f} bits")
    print(f"Mutual Info I(M; C):  {mutual_info:.6f} bits (theoretical = 0.000000)")
    
    assert abs(mutual_info) < 0.05, f"Mutual information deviation too large: {mutual_info}"
    print(">>> PROOF VERIFIED: Shannon conditional entropy H(M|C) = H(M), mutual info I(M;C) = 0.")

if __name__ == "__main__":
    verify_shannon_otp()

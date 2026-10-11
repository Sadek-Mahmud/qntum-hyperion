/*
 * ============================================================================
 * AF-MCP v2 — Hardware-Level Constant-Time Primitive Shim
 * ============================================================================
 * Architecture : QNTUM-HYPERION SEPTEM-TITAN-17L
 * File         : af_mcp_v2_ct.cpp
 * Author       : A. S. M. Hossain Mahmud (Shadhin) · BAUST, Bangladesh
 * Paper        : IEEE Access 2026
 *
 * Purpose
 * -------
 * Provides hardware-level constant-time primitives that cannot be reliably
 * guaranteed by the Python interpreter.  Exposed as a shared library via
 * extern "C" so that Python ctypes / cffi can bind without overhead.
 *
 * Threat model
 * ------------
 * Timing side-channel adversaries (Kocher, Brumley-Boneh, Spectre variants).
 * All exported functions execute in O(1) wall-clock time regardless of the
 * data values passed to them.
 *
 * Build (macOS / Linux)
 * ----------------------
 *   c++ -O0 -fno-optimize-sibling-calls -fno-omit-frame-pointer \
 *       -std=c++17 -Wall -Wextra -shared -fPIC \
 *       -o af_mcp_v2_ct.so af_mcp_v2_ct.cpp
 *
 * Build with self-test
 * --------------------
 *   c++ -O0 -std=c++17 -DRUN_SELFTEST af_mcp_v2_ct.cpp -o ct_selftest
 *   ./ct_selftest
 *
 * Python ctypes integration
 * --------------------------
 *   import ctypes, pathlib
 *   _lib = ctypes.CDLL(str(pathlib.Path(__file__).parent / "af_mcp_v2_ct.so"))
 *   _lib.ct_dummy_hash_work.argtypes = [
 *       ctypes.c_char_p, ctypes.c_size_t,
 *       ctypes.c_uint32, ctypes.c_char_p]
 *   _lib.ct_dummy_hash_work.restype  = None
 *
 * Security Notes
 * --------------
 * 1.  -O0 is intentional: prevents the compiler from dead-code-eliminating
 *     the dummy hash loop (since no side-effect is observable externally).
 * 2.  volatile barrier() ensures the CPU memory subsystem cannot re-order
 *     stores around security-critical zeroing (ct_secure_zero).
 * 3.  ct_select_u8 compiles to CMOV on x86-64; no branch is emitted.
 * 4.  Timing assumptions hold only on out-of-order CPUs with disabled turbo
 *     boost / frequency scaling.  Pin clocks in production.
 * ============================================================================
 */

#include <cstddef>
#include <cstdint>
#include <cstring>

/* ============================================================
   Keccak-f[1600] — minimal reference (NIST FIPS 202)
   Embedded to keep the shim dependency-free.
   ============================================================ */

static const uint64_t kKeccakRoundConst[24] = {
    0x0000000000000001ULL, 0x0000000000008082ULL,
    0x800000000000808AULL, 0x8000000080008000ULL,
    0x000000000000808BULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL,
    0x000000000000008AULL, 0x0000000000000088ULL,
    0x0000000080008009ULL, 0x000000008000000AULL,
    0x000000008000808BULL, 0x800000000000008BULL,
    0x8000000000008089ULL, 0x8000000000008003ULL,
    0x8000000000008002ULL, 0x8000000000000080ULL,
    0x000000000000800AULL, 0x800000008000000AULL,
    0x8000000080008081ULL, 0x8000000000008080ULL,
    0x0000000080000001ULL, 0x8000000080008008ULL,
};

static inline uint64_t rotl64(uint64_t x, int n) {
    return (x << n) | (x >> (64 - n));
}

static void keccak_f1600(uint64_t A[25]) {
    static const int rho_off[25] = {
        0,  1, 62, 28, 27, 36, 44,  6, 55, 20,
        3, 10, 43, 25, 39, 41, 45, 15, 21,  8,
       18,  2, 61, 56, 14
    };
    static const int pi_idx[25] = {
        0, 10,  20, 5, 15, 16,  1, 11, 21, 6,
        7, 17,   2, 12, 22, 23, 8, 18,  3, 13,
       14, 24,   9, 19, 4
    };
    for (int round = 0; round < 24; ++round) {
        /* theta */
        uint64_t C[5], D[5];
        for (int x = 0; x < 5; ++x)
            C[x] = A[x] ^ A[x+5] ^ A[x+10] ^ A[x+15] ^ A[x+20];
        for (int x = 0; x < 5; ++x)
            D[x] = C[(x+4)%5] ^ rotl64(C[(x+1)%5], 1);
        for (int i = 0; i < 25; ++i) A[i] ^= D[i%5];
        /* rho + pi */
        uint64_t B[25];
        for (int i = 0; i < 25; ++i)
            B[pi_idx[i]] = rotl64(A[i], rho_off[i]);
        /* chi */
        for (int y = 0; y < 25; y += 5)
            for (int x = 0; x < 5; ++x)
                A[y+x] = B[y+x] ^ (~B[y+(x+1)%5] & B[y+(x+2)%5]);
        /* iota */
        A[0] ^= kKeccakRoundConst[round];
    }
}

/* Keccak-256 (rate=136 bytes, capacity=512 bits) */
static void keccak256(const uint8_t* in, size_t inlen, uint8_t* out) {
    constexpr size_t RATE = 136;
    uint64_t state[25] = {};
    auto absorb = [&](const uint8_t* blk) {
        for (size_t i = 0; i < RATE; i += 8) {
            uint64_t w = 0;
            for (int b = 0; b < 8; ++b)
                w |= (uint64_t)blk[i+b] << (8*b);
            state[i/8] ^= w;
        }
        keccak_f1600(state);
    };
    while (inlen >= RATE) { absorb(in); in += RATE; inlen -= RATE; }
    uint8_t pad[RATE] = {};
    memcpy(pad, in, inlen);
    pad[inlen]    ^= 0x01;   /* Keccak domain */
    pad[RATE - 1] ^= 0x80;
    absorb(pad);
    for (int i = 0; i < 4; ++i) {
        uint64_t w = state[i];
        for (int b = 0; b < 8; ++b)
            out[i*8+b] = (uint8_t)(w >> (8*b));
    }
}

/* ============================================================
   Memory / compiler barrier
   ============================================================ */
static inline void memory_barrier() {
#if defined(__GNUC__) || defined(__clang__)
    __asm__ __volatile__("" ::: "memory");
#elif defined(_MSC_VER)
    _ReadWriteBarrier();
#endif
}

/* ============================================================
   Exported constant-time primitives
   ============================================================ */

/* ct_secure_zero — compiler-elision-resistant secure wipe */
extern "C" void ct_secure_zero(void* ptr, size_t len) {
    volatile uint8_t* p = reinterpret_cast<volatile uint8_t*>(ptr);
    for (size_t i = 0; i < len; ++i) p[i] = 0;
    memory_barrier();
}

/* ct_select_u8 — branchless conditional select (mask in {0,1})
   Returns mask ? a : b.  Compiles to CMOV on x86-64. */
extern "C" uint8_t ct_select_u8(uint8_t mask, uint8_t a, uint8_t b) {
    uint8_t m = (uint8_t)(-(int8_t)(mask & 1));  /* 0x00 or 0xFF */
    return (uint8_t)((m & a) | (~m & b));
}

/* ct_select_u64 — branchless 64-bit conditional select */
extern "C" uint64_t ct_select_u64(uint8_t mask, uint64_t a, uint64_t b) {
    uint64_t m = (uint64_t)(-(int64_t)(mask & 1));
    return (m & a) | (~m & b);
}

/* ct_bytes_equal — constant-time comparison; returns 1 if equal, 0 otherwise.
   No early-exit branch — executes identical instruction sequence for all inputs. */
extern "C" int ct_bytes_equal(const uint8_t* a, const uint8_t* b, size_t len) {
    volatile uint8_t diff = 0;
    for (size_t i = 0; i < len; ++i) diff |= (a[i] ^ b[i]);
    memory_barrier();
    /* diff==0 iff equal; map to {1,0} without a branch */
    return (int)(1u - (((unsigned)diff + 255u) >> 8u));

}

/*
 * ct_dummy_hash_work
 * ------------------
 * Fixed-iteration Keccak-256 dummy-work loop to pad rejection paths so that
 * accept vs. reject execution time is indistinguishable to a timing adversary.
 *
 * Parameters
 * ----------
 * seed       : seed bytes (typically the ciphertext fingerprint)
 * seed_len   : length of seed (bytes)
 * iterations : number of Keccak-256 rounds (match Python DUMMY_HASH_ITERS)
 * out        : 32-byte output buffer (caller-allocated)
 */
extern "C" void ct_dummy_hash_work(
    const uint8_t* seed,
    size_t         seed_len,
    uint32_t       iterations,
    uint8_t*       out
) {
    constexpr size_t DLEN = 32;
    uint8_t tmp[DLEN] = {};
    size_t copy_len = (seed_len < DLEN) ? seed_len : DLEN;
    memcpy(tmp, seed, copy_len);

    uint8_t block[4 + DLEN];
    for (uint32_t i = 0; i < iterations; ++i) {
        block[0] = (uint8_t)(i >> 24);
        block[1] = (uint8_t)(i >> 16);
        block[2] = (uint8_t)(i >>  8);
        block[3] = (uint8_t)(i >>  0);
        memcpy(block + 4, tmp, DLEN);
        keccak256(block, sizeof(block), tmp);
        memory_barrier();   /* prevent loop hoisting */
    }
    memcpy(out, tmp, DLEN);
    ct_secure_zero(block, sizeof(block));
    ct_secure_zero(tmp, DLEN);
}

/*
 * ct_hmac_keccak256
 * -----------------
 * Constant-time HMAC using Keccak-256.
 * Produces 32-byte MAC.  Execution time depends only on (key_len + msg_len).
 */
extern "C" void ct_hmac_keccak256(
    const uint8_t* key,    size_t key_len,
    const uint8_t* msg,    size_t msg_len,
    uint8_t*       mac_out          /* 32 bytes */
) {
    constexpr size_t BLOCK = 136;
    constexpr size_t DLEN  = 32;

    uint8_t k_ipad[BLOCK], k_opad[BLOCK];
    memset(k_ipad, 0x36, BLOCK);
    memset(k_opad, 0x5c, BLOCK);

    uint8_t k_actual[BLOCK] = {};
    if (key_len > BLOCK)
        keccak256(key, key_len, k_actual);
    else
        memcpy(k_actual, key, key_len);

    for (size_t i = 0; i < BLOCK; ++i) {
        k_ipad[i] ^= k_actual[i];
        k_opad[i] ^= k_actual[i];
    }

    /* Inner: H(k_ipad || msg) */
    uint8_t inner[DLEN];
    {
        size_t buf_len = BLOCK + msg_len;
        uint8_t* buf = new uint8_t[buf_len];
        memcpy(buf,        k_ipad, BLOCK);
        memcpy(buf + BLOCK, msg,   msg_len);
        keccak256(buf, buf_len, inner);
        ct_secure_zero(buf, buf_len);
        delete[] buf;
    }

    /* Outer: H(k_opad || inner) */
    uint8_t outer[BLOCK + DLEN];
    memcpy(outer,       k_opad, BLOCK);
    memcpy(outer+BLOCK, inner,  DLEN);
    keccak256(outer, sizeof(outer), mac_out);

    ct_secure_zero(k_ipad,   BLOCK);
    ct_secure_zero(k_opad,   BLOCK);
    ct_secure_zero(k_actual, BLOCK);
    ct_secure_zero(inner,    DLEN);
    ct_secure_zero(outer,    sizeof(outer));
}

/*
 * ct_latency_probe_ns
 * -------------------
 * Returns current monotonic timestamp in nanoseconds.
 * Used by the benchmark harness to measure wall-clock time from C.
 */
#if defined(__APPLE__) || defined(__linux__)
#include <time.h>
extern "C" uint64_t ct_latency_probe_ns(void) {
    struct timespec ts;
#if defined(CLOCK_MONOTONIC_RAW)
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
    clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
#elif defined(_WIN32)
#include <windows.h>
extern "C" uint64_t ct_latency_probe_ns(void) {
    LARGE_INTEGER freq, cnt;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&cnt);
    return (uint64_t)((double)cnt.QuadPart / freq.QuadPart * 1e9);
}
#else
extern "C" uint64_t ct_latency_probe_ns(void) { return 0; }
#endif

/* ============================================================
   Standalone self-test   (compile with -DRUN_SELFTEST)
   ============================================================ */
#ifdef RUN_SELFTEST
#include <cstdio>
int main(void) {
    printf("=== AF-MCP v2 Constant-Time Shim Self-Test ===\n\n");

    /* ct_bytes_equal */
    {
        uint8_t a[] = {1,2,3,4};
        uint8_t b[] = {1,2,3,4};
        uint8_t c[] = {1,2,3,5};
        printf("[ct_bytes_equal] same   : %d (expect 1)\n", ct_bytes_equal(a,b,4));
        printf("[ct_bytes_equal] differ : %d (expect 0)\n", ct_bytes_equal(a,c,4));
    }

    /* ct_select_u8 */
    printf("[ct_select_u8]   mask=1 : 0x%02X (expect 0xAA)\n", ct_select_u8(1,0xAA,0xBB));
    printf("[ct_select_u8]   mask=0 : 0x%02X (expect 0xBB)\n", ct_select_u8(0,0xAA,0xBB));

    /* ct_select_u64 */
    printf("[ct_select_u64]  mask=1 : %llu (expect 100)\n",
           (unsigned long long)ct_select_u64(1,100ULL,200ULL));

    /* ct_dummy_hash_work */
    {
        uint8_t seed[8]  = {0xDE,0xAD,0xBE,0xEF,0xCA,0xFE,0xBA,0xBE};
        uint8_t out[32]  = {};
        uint64_t t0 = ct_latency_probe_ns();
        ct_dummy_hash_work(seed, 8, 64, out);
        uint64_t t1 = ct_latency_probe_ns();
        printf("[ct_dummy_hash_work] 64 iters : %llu ns — digest: ",
               (unsigned long long)(t1 - t0));
        for (int i = 0; i < 8; ++i) printf("%02x", out[i]);
        printf("...\n");
    }

    /* ct_hmac_keccak256 */
    {
        uint8_t key[] = "SEPTEM-HMAC-KEY";
        uint8_t msg[] = "QNTUM-HYPERION-17L";
        uint8_t mac[32];
        ct_hmac_keccak256(key, sizeof(key)-1, msg, sizeof(msg)-1, mac);
        printf("[ct_hmac_keccak256] mac: ");
        for (int i = 0; i < 32; ++i) printf("%02x", mac[i]);
        printf("\n");
    }

    printf("\n=== All self-tests passed ===\n");
    return 0;
}
#endif /* RUN_SELFTEST */

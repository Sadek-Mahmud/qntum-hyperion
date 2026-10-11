"""
================================================================================
AF-MCP v2 — Benchmark Harness
================================================================================
Architecture : QNTUM-HYPERION SEPTEM-TITAN-17L
File         : af_mcp_benchmark.py
Author       : A. S. M. Hossain Mahmud (Shadhin) · BAUST, Bangladesh
Paper        : IEEE Access 2026

SLA Targets
-----------
  T-1 (Active Tier)   : p99 < 1 ms
  T-2 (Failover Tier) : p99 < 3 ms
  T-3 (Cold Tier)     : p99 < 5 ms

Usage
-----
  python3 af_mcp_benchmark.py                    # default 200 iterations
  python3 af_mcp_benchmark.py --iters 500 --seed 42
  python3 af_mcp_benchmark.py --tier t1          # only benchmark T-1
  python3 af_mcp_benchmark.py --export bench_results.json

C++ shim (optional)
-------------------
  Build:  c++ -O0 -std=c++17 -shared -fPIC -o qntum_pqc/af_mcp_v2_ct.so \
               qntum_pqc/af_mcp_v2_ct.cpp
  The harness auto-detects the .so and uses ct_latency_probe_ns() for
  nanosecond-precision timing instead of Python's time.perf_counter_ns().
================================================================================
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import pathlib
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional C++ shim binding
# ---------------------------------------------------------------------------
_LIB: Optional[ctypes.CDLL] = None

def _load_ct_shim() -> Optional[ctypes.CDLL]:
    """Try to load the compiled constant-time shim shared library."""
    so_name = "af_mcp_v2_ct.so" if platform.system() != "Windows" else "af_mcp_v2_ct.dll"
    so_path = pathlib.Path(__file__).parent / so_name
    if not so_path.exists():
        return None
    try:
        lib = ctypes.CDLL(str(so_path))
        lib.ct_latency_probe_ns.restype = ctypes.c_uint64
        lib.ct_latency_probe_ns.argtypes = []
        lib.ct_dummy_hash_work.restype = None
        lib.ct_dummy_hash_work.argtypes = [
            ctypes.c_char_p, ctypes.c_size_t,
            ctypes.c_uint32, ctypes.c_char_p,
        ]
        return lib
    except Exception:
        return None


def _now_ns() -> int:
    """Return monotonic time in nanoseconds — uses C shim if available."""
    if _LIB is not None:
        return int(_LIB.ct_latency_probe_ns())
    return time.perf_counter_ns()


# ---------------------------------------------------------------------------
# Pipeline import
# ---------------------------------------------------------------------------
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from qntum_pqc.kem import HyperionKEM
from qntum_pqc.af_mcp_v2 import AdaptiveFailoverCryptoPipeline, PipelineTier, build_pipeline

logging.basicConfig(level=logging.WARNING)  # suppress verbose pipeline logs

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TierResult:
    name: str
    sla_ms: float          # SLA target (milliseconds)
    latencies_us: List[float] = field(default_factory=list)

    # Derived stats (populated after run)
    n: int = 0
    mean_us: float = 0.0
    median_us: float = 0.0
    p95_us: float = 0.0
    p99_us: float = 0.0
    min_us: float = 0.0
    max_us: float = 0.0
    std_us: float = 0.0
    sla_pass: bool = True

    def compute_stats(self) -> None:
        if not self.latencies_us:
            return
        s = sorted(self.latencies_us)
        self.n = len(s)
        self.mean_us   = statistics.mean(s)
        self.median_us = statistics.median(s)
        self.p95_us    = s[int(0.95 * len(s))]
        self.p99_us    = s[int(0.99 * len(s))]
        self.min_us    = s[0]
        self.max_us    = s[-1]
        self.std_us    = statistics.stdev(s) if len(s) > 1 else 0.0
        self.sla_pass  = (self.p99_us / 1_000) <= self.sla_ms

    def report_line(self) -> str:
        status = "✅ PASS" if self.sla_pass else "❌ FAIL"
        return (
            f"  {self.name:<12} | "
            f"n={self.n:>4} | "
            f"mean={self.mean_us/1000:>6.2f}ms | "
            f"p99={self.p99_us/1000:>6.2f}ms | "
            f"min={self.min_us/1000:>5.2f}ms | "
            f"max={self.max_us/1000:>5.2f}ms | "
            f"SLA<{self.sla_ms:.0f}ms {status}"
        )


@dataclass
class BenchmarkReport:
    platform_info: Dict[str, str]
    iters: int
    warmup: int
    c_shim_loaded: bool
    tier_results: Dict[str, TierResult]
    global_throughput_ops_sec: float = 0.0
    all_sla_pass: bool = True

    def print(self) -> None:
        print("\n" + "=" * 90)
        print("  AF-MCP v2 — Benchmark Report")
        print("  QNTUM-HYPERION SEPTEM-TITAN-17L")
        print("=" * 90)
        print(f"  Platform  : {self.platform_info.get('system')} "
              f"{self.platform_info.get('machine')} — {self.platform_info.get('processor')}")
        print(f"  Python    : {self.platform_info.get('python')}")
        print(f"  C++ shim  : {'loaded ✅' if self.c_shim_loaded else 'not found ⚠️  (using Python timer)'}")
        print(f"  Iterations: {self.iters} (+ {self.warmup} warmup)\n")

        print(f"  {'Tier':<12} | {'n':>4} | {'mean':>9} | {'p99':>8} | {'min':>7} | {'max':>7} | SLA target")
        print("  " + "-" * 80)
        for tr in self.tier_results.values():
            print(tr.report_line())

        print("\n  " + "-" * 80)
        verdict = "✅ ALL SLA TARGETS MET" if self.all_sla_pass else "❌ SOME SLA TARGETS MISSED"
        print(f"  Global throughput : {self.global_throughput_ops_sec:.1f} ops/sec")
        print(f"  Overall verdict   : {verdict}")
        print("=" * 90 + "\n")

    def to_json(self) -> dict:
        d = {
            "platform": self.platform_info,
            "iters": self.iters,
            "warmup": self.warmup,
            "c_shim_loaded": self.c_shim_loaded,
            "global_throughput_ops_sec": self.global_throughput_ops_sec,
            "all_sla_pass": self.all_sla_pass,
            "tiers": {}
        }
        for k, tr in self.tier_results.items():
            d["tiers"][k] = {
                "n": tr.n,
                "mean_us": tr.mean_us,
                "median_us": tr.median_us,
                "p95_us": tr.p95_us,
                "p99_us": tr.p99_us,
                "min_us": tr.min_us,
                "max_us": tr.max_us,
                "std_us": tr.std_us,
                "sla_ms": tr.sla_ms,
                "sla_pass": tr.sla_pass,
            }
        return d


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

class AfMcpBenchmark:
    """
    Benchmark harness for the AF-MCP v2 pipeline.

    Measures per-tier latency by injecting controlled fault conditions to
    trigger T-2 and T-3 tier promotions, then measuring their latency.
    """

    SLA_MS = {"T-1": 1.0, "T-2": 3.0, "T-3": 5.0}

    def __init__(self, iters: int = 200, warmup: int = 20, seed: int = 0):
        self.iters  = iters
        self.warmup = warmup
        self.seed   = seed

        global _LIB
        _LIB = _load_ct_shim()

        print(f"\n[Benchmark] Generating HyperionKEM key pair (seed={seed})…")
        t0 = _now_ns()
        self.pk, self.sk = HyperionKEM.keygen()
        t1 = _now_ns()
        print(f"[Benchmark] Keygen: {(t1-t0)/1e6:.2f} ms")

    # ------------------------------------------------------------------
    # Helper: encapsulate + record T-1 decapsulation latency
    # ------------------------------------------------------------------
    def _bench_t1(self) -> List[float]:
        """Benchmark T-1 (Active Tier: L1+L3 only, nominal traffic)."""
        pipeline = build_pipeline(self.sk, enable_benchmarking=False)
        latencies: List[float] = []

        print(f"[Benchmark] T-1 warm-up ({self.warmup} iters)…")
        for _ in range(self.warmup):
            ct, _ = HyperionKEM.encaps(self.pk)
            pipeline.decaps(ct)

        print(f"[Benchmark] T-1 measurement ({self.iters} iters)…")
        for _ in range(self.iters):
            ct, _ = HyperionKEM.encaps(self.pk)
            t0 = _now_ns()
            pipeline.decaps(ct)
            t1 = _now_ns()
            latencies.append((t1 - t0) / 1_000.0)   # → microseconds

        return latencies

    # ------------------------------------------------------------------
    # Helper: measure T-2 failover latency using pipeline's internal
    # benchmark collector (after forcing anomaly state)
    # ------------------------------------------------------------------
    def _bench_t2(self) -> List[float]:
        """Benchmark T-2 (Failover Tier: QAC + CSIDH) by injecting anomalies."""
        from qntum_pqc.af_mcp_v2 import ThreatLevel

        pipeline = build_pipeline(self.sk, enable_benchmarking=True)
        latencies: List[float] = []

        # Warm up T-1 first
        for _ in range(self.warmup):
            ct, _ = HyperionKEM.encaps(self.pk)
            pipeline.decaps(ct)

        # Force into ANOMALY state so T-2 is activated next call
        with pipeline._lock:
            pipeline._state_machine.threat_level = ThreatLevel.ANOMALY
            pipeline._current_tier = PipelineTier.FAILOVER

        print(f"[Benchmark] T-2 measurement ({self.iters} iters)…")
        for _ in range(self.iters):
            ct, _ = HyperionKEM.encaps(self.pk)
            t0 = _now_ns()
            pipeline.decaps(ct)
            t1 = _now_ns()
            latencies.append((t1 - t0) / 1_000.0)
            # Keep tier in failover — reset if accidentally promoted
            with pipeline._lock:
                if pipeline._current_tier == PipelineTier.ACTIVE:
                    pipeline._current_tier = PipelineTier.FAILOVER
                    pipeline._state_machine.threat_level = ThreatLevel.ANOMALY

        return latencies

    # ------------------------------------------------------------------
    # Helper: measure T-3 cold tier latency
    # ------------------------------------------------------------------
    def _bench_t3(self) -> List[float]:
        """Benchmark T-3 (Cold Tier: full 17-layer verification)."""
        from qntum_pqc.af_mcp_v2 import ThreatLevel

        pipeline = build_pipeline(self.sk, enable_benchmarking=True)
        latencies: List[float] = []

        # Force into BREACH state so T-3 cold tier is activated
        with pipeline._lock:
            pipeline._state_machine.threat_level = ThreatLevel.BREACH
            pipeline._current_tier = PipelineTier.COLD

        print(f"[Benchmark] T-3 warm-up ({self.warmup // 2} iters) — may be slow…")
        for _ in range(self.warmup // 2):
            ct, _ = HyperionKEM.encaps(self.pk)
            pipeline.decaps(ct)

        print(f"[Benchmark] T-3 measurement ({self.iters} iters)…")
        for _ in range(self.iters):
            ct, _ = HyperionKEM.encaps(self.pk)
            t0 = _now_ns()
            pipeline.decaps(ct)
            t1 = _now_ns()
            latencies.append((t1 - t0) / 1_000.0)
            with pipeline._lock:
                if pipeline._current_tier == PipelineTier.ACTIVE:
                    pipeline._current_tier = PipelineTier.COLD
                    pipeline._state_machine.threat_level = ThreatLevel.BREACH

        return latencies

    # ------------------------------------------------------------------
    # Public run method
    # ------------------------------------------------------------------
    def run(
        self,
        tiers: Optional[List[str]] = None,
        export_path: Optional[str]  = None,
    ) -> BenchmarkReport:

        tiers = tiers or ["t1", "t2", "t3"]
        tier_results: Dict[str, TierResult] = {}

        tier_dispatch = {
            "t1": ("T-1", 1.0, self._bench_t1),
            "t2": ("T-2", 3.0, self._bench_t2),
            "t3": ("T-3", 5.0, self._bench_t3),
        }

        total_t0 = _now_ns()
        for key in tiers:
            name, sla, fn = tier_dispatch[key]
            print(f"\n{'─'*60}")
            print(f"  Benchmarking {name} (SLA < {sla} ms)…")
            print(f"{'─'*60}")
            lats = fn()
            tr = TierResult(name=name, sla_ms=sla, latencies_us=lats)
            tr.compute_stats()
            tier_results[key] = tr
        total_t1 = _now_ns()

        total_iters = sum(len(tr.latencies_us) for tr in tier_results.values())
        elapsed_s = (total_t1 - total_t0) / 1e9
        throughput = total_iters / elapsed_s if elapsed_s > 0 else 0.0

        report = BenchmarkReport(
            platform_info={
                "system":    platform.system(),
                "machine":   platform.machine(),
                "processor": platform.processor() or "N/A",
                "python":    platform.python_version(),
            },
            iters=self.iters,
            warmup=self.warmup,
            c_shim_loaded=(_LIB is not None),
            tier_results=tier_results,
            global_throughput_ops_sec=throughput,
            all_sla_pass=all(tr.sla_pass for tr in tier_results.values()),
        )

        report.print()

        if export_path:
            with open(export_path, "w") as f:
                json.dump(report.to_json(), f, indent=2)
            print(f"[Benchmark] Results exported → {export_path}\n")

        return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AF-MCP v2 Pipeline Benchmark Harness (SEPTEM-TITAN-17L)"
    )
    p.add_argument("--iters",  type=int, default=200,
                   help="Measurement iterations per tier (default: 200)")
    p.add_argument("--warmup", type=int, default=20,
                   help="Warm-up iterations before measurement (default: 20)")
    p.add_argument("--seed",   type=int, default=0,
                   help="Random seed (for reproducibility)")
    p.add_argument("--tier",   type=str, default=None,
                   choices=["t1", "t2", "t3"],
                   help="Benchmark a single tier only (default: all three)")
    p.add_argument("--export", type=str, default=None, metavar="FILE",
                   help="Export results to JSON file")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    harness = AfMcpBenchmark(
        iters=args.iters,
        warmup=args.warmup,
        seed=args.seed,
    )
    tiers = [args.tier] if args.tier else ["t1", "t2", "t3"]
    harness.run(tiers=tiers, export_path=args.export)

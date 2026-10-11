#!/usr/bin/env bash
set -e
echo "Building C++ Hardware Constant-Time Shim (af_mcp_v2_ct.so)..."
c++ -O0 -fno-optimize-sibling-calls -std=c++17 -shared -fPIC \
    -o src/qntum_pqc/af_mcp_v2_ct.so src/qntum_pqc/af_mcp_v2_ct.cpp
echo "Build complete: src/qntum_pqc/af_mcp_v2_ct.so"

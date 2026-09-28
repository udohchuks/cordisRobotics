#!/bin/bash
# Full replication + new experiments on a second machine.
cd "$(dirname "$0")/.."
export RTVLA_RESULTS=${RTVLA_RESULTS:-$PWD/results_pc}
mkdir -p "$RTVLA_RESULTS"
L="$RTVLA_RESULTS/run.log"
echo "start $(date -u) $(nproc) cpus" > "$L"
python3 experiments/rust_only.py 300 > "$RTVLA_RESULTS/rust_only.log" 2>&1; echo "rust_only done $(date -u)" >> "$L"
python3 experiments/t3_faults.py 50 > "$RTVLA_RESULTS/t3.log" 2>&1; echo "t3 done $(date -u)" >> "$L"
python3 experiments/t6_epoch.py 50 > "$RTVLA_RESULTS/t6.log" 2>&1; echo "t6 done $(date -u)" >> "$L"
python3 experiments/t4_midswap.py 10 > "$RTVLA_RESULTS/t4.log" 2>&1; echo "t4 done $(date -u)" >> "$L"
python3 experiments/t2_repair.py 10 > "$RTVLA_RESULTS/t2.log" 2>&1; echo "t2 done $(date -u)" >> "$L"
python3 experiments/t1_liveness.py 60 2 > "$RTVLA_RESULTS/t1.log" 2>&1; echo "t1 done $(date -u)" >> "$L"
echo "all done $(date -u)" >> "$L"

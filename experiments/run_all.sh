#!/bin/bash
cd "$(dirname "$0")/.."
echo "start $(date -u)"
python3 experiments/t3_faults.py 50 > results/t3.log 2>&1; echo "t3 done $(date -u)"
python3 experiments/t2_repair.py 20 > results/t2.log 2>&1; echo "t2 done $(date -u)"
python3 experiments/t1_liveness.py 60 3 > results/t1.log 2>&1; echo "t1 done $(date -u)"

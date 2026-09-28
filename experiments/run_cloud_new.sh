#!/bin/bash
cd "$(dirname "$0")/.."
echo "start $(date -u)" > results/new.log
python3 experiments/t6_epoch.py 50 > results/t6.log 2>&1; echo "t6 done $(date -u)" >> results/new.log
python3 experiments/t4_midswap.py 20 > results/t4.log 2>&1; echo "t4 done $(date -u)" >> results/new.log

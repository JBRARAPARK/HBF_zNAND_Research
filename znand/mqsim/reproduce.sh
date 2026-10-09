#!/bin/sh
set -eu
# Run from NAND_Prefetch_Model; uses a fresh directory supplied by the caller.
base=$(pwd)
target=${1:?Usage: sh znand/mqsim/reproduce.sh /path/to/new/mqsim-checkout}
git clone https://github.com/CMU-SAFARI/MQSim.git "$target"
git -C "$target" checkout 51f0f2d3fed92d88ef4a0fa61a38024b07bf9d16
git -C "$target" apply "$base/znand/mqsim/export.patch"
make -C "$target" -j4
cp znand/mqsim/ssdconfig.xml "$target/znand_config.xml"
cp znand/mqsim/workload.xml "$target/znand_workload.xml"
(cd "$target" && MQSIM_L2P_EXPORT=precondition.csv MQSIM_SNAPSHOT_ONLY=1 ./MQSim -i znand_config.xml -w znand_workload.xml)
python3 znand/mqsim/convert.py "$target/precondition.csv" "$target/snapshot.json" --revision 51f0f2d3fed92d88ef4a0fa61a38024b07bf9d16

# sta.tcl
# OpenSTA static timing analysis for a synthesized single-output netlist.
#   sta -liberty <your liberty> -read_verilog rtl/optimized/y0_final.v \
#       -top y0 -script scripts/sta.tcl
#
# NOTE: the liberty file (NangateOpenCellLibrary_typical.lib) is NOT
# redistributed in this repo; supply your local copy. The original script
# analyzed result/netlist_mapped.v (full SB); it is updated here to analyze
# the curated single-output final netlist.
read_liberty NangateOpenCellLibrary_typical.lib
read_verilog rtl/optimized/y0_final.v
link_design y0

# 纯组合逻辑时序约束
set_input_delay 0.0 [all_inputs]
set_output_delay 0.0 [all_outputs]
set_max_delay 1000 [all_outputs]

# 报告前3条最慢路径
puts "====================================="
puts "  最终实际关键路径延时 D_sta (ps)"
puts "====================================="
report_checks -max_paths 3 -format full

puts "\n====================================="
puts "  最差路径延迟"
puts "====================================="
report_worst_slack -min

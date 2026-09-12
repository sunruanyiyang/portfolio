# optimizer/run_yosys.py
#
# NOTE (repository curation): this driver runs `yosys -s scripts/run.ys` from
# the repository root. In the curated layout the Yosys scripts were renamed
# (scripts/run.ys -> scripts/abc_optimize.ys, which now points at
# rtl/optimized/y0_final.v). If you re-run the search pipeline, adjust the
# script name here and make sure the script's read_verilog target matches the
# file that search/generator.py emits (rtl/current_y0.v).
import subprocess
import os

def run():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        ["yosys", "-s", "scripts/run.ys"],
        cwd=root_dir,
        capture_output=True,
        text=True
    )
    
    # 保存日志
    os.makedirs("results", exist_ok=True)
    with open("results/last_run.log", "w") as f:
        f.write(result.stdout)
        f.write(result.stderr)
    
    if result.returncode != 0:
        raise RuntimeError(f"Yosys运行失败: {result.stderr}")
    return result.stdout
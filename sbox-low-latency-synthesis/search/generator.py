# optimizer/generator.py
from truth import Y0_TRUTH

def generate(order):
    layer_vars = list(order)
    num_layers = len(layer_vars)
    rest_vars = [i for i in range(6) if i not in layer_vars]

    # 生成所有叶子子函数：第一层变量对应最高位，最后一层对应最低位
    sub_funcs = {}
    for x in range(64):
        if not ((Y0_TRUTH >> x) & 1):
            continue

        # 计算叶子函数索引
        key = 0
        for i, var in enumerate(layer_vars):
            bit_val = (x >> var) & 1
            key |= bit_val << (num_layers - 1 - i)

        # 生成剩余变量的与项
        term = []
        for var in rest_vars:
            term.append(f"x{var}" if (x >> var) & 1 else f"~x{var}")

        key_name = f"f_{key:0{num_layers}b}"
        if key_name not in sub_funcs:
            sub_funcs[key_name] = []
        sub_funcs[key_name].append(" & ".join(term))

    # 拼接 Verilog
    lines = [
        "module y0 (",
        "    input  [5:0] x,",
        "    output y0",
        ");",
        ""
    ]
    for i in range(6):
        lines.append(f"wire x{i} = x[{i}];")
    lines.append("")

    # 声明叶子函数
    for name in sorted(sub_funcs.keys()):
        terms = sub_funcs[name]
        if not terms:
            lines.append(f"wire {name} = 1'b0;")
        elif len(terms) == 1:
            lines.append(f"wire {name} = {terms[0]};")
        else:
            rhs = " |\n    ".join(terms)
            lines.append(f"wire {name} =\n    {rhs};")
        lines.append("")

    # 逐层合并MUX：从最内层（最后一个变量）到最外层（第一个变量）
    current_signals = sorted(sub_funcs.keys())
    for layer_idx in range(num_layers - 1, -1, -1):
        select_var = layer_vars[layer_idx]
        next_signals = []
        for i in range(0, len(current_signals), 2):
            low = current_signals[i]
            high = current_signals[i+1]
            is_final = (layer_idx == 0) and (len(next_signals) == 0)
            
            if is_final:
                lines.append(f"assign y0 = x{select_var} ? {high} : {low};")
            else:
                wire_name = f"mux_l{layer_idx}_{i//2}"
                lines.append(f"wire {wire_name} = x{select_var} ? {high} : {low};")
                next_signals.append(wire_name)
        current_signals = next_signals
        lines.append("")

    lines.append("endmodule")

    # 写入文件
    with open("../rtl/current_y0.v", "w") as f:
        f.write("\n".join(lines))
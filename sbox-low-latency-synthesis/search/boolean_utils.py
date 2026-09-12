# optimizer/boolean_utils.py 完整全量版
MASK64 = 0xFFFFFFFFFFFFFFFF

# 6个原始输入对应的64位掩码（x=0对应第0位）
INPUT_MASKS = {
    0: 0xAAAAAAAAAAAAAAAA,  # x0: 最低位，交替01
    1: 0xCCCCCCCCCCCCCCCC,  # x1: 每2位翻转
    2: 0xF0F0F0F0F0F0F0F0,  # x2: 每4位翻转
    3: 0xFF00FF00FF00FF00,  # x3: 每8位翻转
    4: 0xFFFF0000FFFF0000,  # x4: 每16位翻转
    5: 0xFFFFFFFF00000000,  # x5: 每32位翻转
}

def b_not(f):
    """64位按位取反"""
    return (~f) & MASK64

def b_and(f, g):
    return f & g

def b_or(f, g):
    return f | g

def b_xor(f, g):
    return f ^ g

def hamming(f, target):
    """计算两个函数的汉明距离（不同的位数）"""
    return bin(f ^ target).count('1')

# ---------- 门模板：对应库里的复合门 ----------
def gate_aoi21(a, b, c):
    """AOI21: ~( (a&b) | c )  与或非"""
    return b_not(b_or(b_and(a, b), c))

def gate_oai21(a, b, c):
    """OAI21: ~( (a|b) & c )  或与非"""
    return b_not(b_and(b_or(a, b), c))

def gate_nand2(a, b):
    """NAND2: ~(a&b)"""
    return b_not(b_and(a, b))

def gate_nor2(a, b):
    """NOR2: ~(a|b)"""
    return b_not(b_or(a, b))

# 可用门模板列表（优先放低延时的）
GATE_TEMPLATES = [
    ("OAI21", gate_oai21),
    ("AOI21", gate_aoi21),
    ("NAND2", gate_nand2),
    ("NOR2", gate_nor2),
]

# ---------- 真值表拆分与掩码生成工具 ----------
def generate_input_masks(n):
    """生成n输入布尔函数对应的输入掩码（n=5对应32位）"""
    masks = []
    for i in range(n):
        period = 1 << (i + 1)
        half = 1 << i
        mask = 0
        for block in range((1 << n) // period):
            block_base = block * period
            for bit in range(half):
                mask |= 1 << (block_base + half + bit)
        masks.append(mask)
    return masks

def split_6to5(target_64, split_var):
    """
    把6输入真值表按指定变量拆成两个5输入子真值表
    返回 (f0_32, f1_32, rest_vars)
    f0: split_var=0 时的子函数，32位
    f1: split_var=1 时的子函数，32位
    rest_vars: 剩余5个变量的原序号
    """
    rest_vars = [i for i in range(6) if i != split_var]
    f0 = 0
    f1 = 0
    
    for x_6 in range(64):
        split_bit = (x_6 >> split_var) & 1
        
        # 把剩余变量压缩成5位数值
        val_5 = 0
        for idx, var in enumerate(rest_vars):
            val_5 |= ((x_6 >> var) & 1) << idx
        
        out_bit = (target_64 >> x_6) & 1
        if split_bit == 0:
            f0 |= out_bit << val_5
        else:
            f1 |= out_bit << val_5
    
    return f0, f1, rest_vars
# ---------- 3输入函数最优复合门匹配 ----------
def match_3input_gate(target_8bit, var_names):
    """
    尝试用单级OAI21/AOI21实现3输入布尔函数
    target_8bit: 8位真值表（3输入对应8个最小项）
    var_names: 3个输入变量的名字，比如 ["x0", "x1", "x3"]
    返回: (gate_type, expression_str)，不能实现返回None
    """
    full_mask = 0xFF
    target = target_8bit & full_mask
    
    # 生成3个输入的8位掩码
    masks = [
        0b10101010,  # 第0位变量
        0b11001100,  # 第1位变量
        0b11110000,  # 第2位变量
    ]
    
    # 枚举每个变量作为单端c，剩下两个作为并联a/b
    for c_idx in range(3):
        c_mask = masks[c_idx]
        a_idx, b_idx = [i for i in range(3) if i != c_idx]
        a_mask = masks[a_idx]
        b_mask = masks[b_idx]
        
        c_name = var_names[c_idx]
        a_name = var_names[a_idx]
        b_name = var_names[b_idx]
        
        # 枚举每个输入的极性（原变量/反变量）
        for a_neg in [False, True]:
            a = ~a_mask & full_mask if a_neg else a_mask
            a_str = f"~{a_name}" if a_neg else a_name
            
            for b_neg in [False, True]:
                b = ~b_mask & full_mask if b_neg else b_mask
                b_str = f"~{b_name}" if b_neg else b_name
                
                for c_neg in [False, True]:
                    c = ~c_mask & full_mask if c_neg else c_mask
                    c_str = f"~{c_name}" if c_neg else c_name
                    
                    # 尝试AOI21: ~((a&b) | c)
                    aoi_out = ~(((a & b) | c)) & full_mask
                    if aoi_out == target:
                        expr = f"~(({a_str} & {b_str}) | {c_str})"
                        return ("AOI21", expr)
                    
                    # 尝试OAI21: ~((a|b) & c)
                    oai_out = ~(((a | b) & c)) & full_mask
                    if oai_out == target:
                        expr = f"~(({a_str} | {b_str}) & {c_str})"
                        return ("OAI21", expr)
    
    # 单级复合门实现不了
    return None

def split_6to3(target_64, order):
    """
    把6输入真值表按三层拆分顺序，拆成8个3输入叶子函数
    order: 三层拆分变量顺序，比如 (2,1,0)
    返回: (leaf_truths, rest_vars)
        leaf_truths: 长度为8的列表，每个元素是8位叶子真值表
        rest_vars: 剩余3个叶子变量的原序号
    """
    layer_vars = list(order)
    rest_vars = [i for i in range(6) if i not in layer_vars]
    
    leaf_truths = [0 for _ in range(8)]
    
    for x_6 in range(64):
        # 计算三层选择信号对应的叶子索引
        leaf_idx = 0
        for i, var in enumerate(layer_vars):
            bit = (x_6 >> var) & 1
            leaf_idx |= bit << (2 - i)  # 第一层对应最高位
        
        # 计算叶子内部3位值
        val_3 = 0
        for idx, var in enumerate(rest_vars):
            val_3 |= ((x_6 >> var) & 1) << idx
        
        out_bit = (target_64 >> x_6) & 1
        leaf_truths[leaf_idx] |= out_bit << val_3
    
    return leaf_truths, rest_vars
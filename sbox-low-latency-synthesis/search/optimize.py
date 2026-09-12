# optimizer/optimize.py
from itertools import permutations
from generator import generate
from run_yosys import run
from parse import get_delay, get_cell_count
import os
import csv

def main():
    results = []
    total = 30
    current = 0
    
    print("=== 开始搜索最优两层香农拆分顺序 ===")
    print(f"共 {total} 种组合，预计几分钟完成\n")
    
    for order in permutations(range(6), 2):
        current += 1
        v1, v2 = order
        print(f"[{current}/{total}] 测试顺序: x{v1} → x{v2}", end=" ... ")
        
        try:
            # 1. 生成RTL
            generate(order)
            
            # 2. 跑综合
            log = run()
            
            # 3. 解析结果
            delay = get_delay(log)
            cells = get_cell_count(log)
            
            if delay is None:
                print("解析失败")
                continue
            
            results.append((delay, cells, order))
            print(f"延时: {delay:.2f} ps, 单元数: {cells}")
            
        except Exception as e:
            print(f"运行失败: {str(e)}")
            continue
    
    # 按延时从小到大排序
    results.sort(key=lambda x: x[0])
    
    # 打印排名
    print("\n=== 最终排名（延时从低到高） ===")
    print(f"{'排名':<4} {'第一层':<6} {'第二层':<6} {'延时(ps)':<10} {'单元数':<6}")
    print("-" * 40)
    for i, (delay, cells, order) in enumerate(results[:10], 1):
        v1, v2 = order
        print(f"{i:<4} x{v1:<5} x{v2:<5} {delay:<10.2f} {cells:<6}")
    
    # 保存完整结果到csv
    os.makedirs("results", exist_ok=True)
    with open("results/all_results.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "layer1", "layer2", "delay_ps", "cell_count"])
        for i, (delay, cells, order) in enumerate(results, 1):
            writer.writerow([i, order[0], order[1], delay, cells])
    
    print(f"\n完整结果已保存到 optimizer/results/all_results.csv")

if __name__ == "__main__":
    main()
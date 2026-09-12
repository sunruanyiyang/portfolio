// ============================================================
// y0 - final optimized netlist (full Nangate 45nm library)
//   Truth table: 0x45D3356F02C1D7D8
//   Delay:       123.03 ps (STA with full Nangate library)
//   Gates:       27 (INV×8, NAND2×4, NAND3×4, NAND4×3,
//                     NOR2×2, AND2×1, AOI21×2, OAI21×4, OAI22×1)
//   Depth:       5
//   Area:        24.96
//   Flow:        &deepsyn -T 5 -S 35; &if -K 3; &st; &get; map; topo
//   Verified:    ABC cec + 64-input Python simulation
// ============================================================
module y0 (
    input  [5:0] x,
    output y0
);
  wire new_n8, new_n9, new_n10, new_n11, new_n12, new_n13, new_n14, new_n15,
    new_n16, new_n17, new_n18, new_n19, new_n20, new_n21, new_n22, new_n23,
    new_n24, new_n25, new_n26, new_n27, new_n28, new_n29, new_n30, new_n31,
    new_n32, new_n33;
  INV_X1   g00(.A(x[3]), .ZN(new_n8));
  OAI21_X1 g01(.A(new_n8), .B1(x[1]), .B2(x[4]), .ZN(new_n9));
  NAND2_X1 g02(.A1(x[1]), .A2(x[4]), .ZN(new_n10));
  NAND3_X1 g03(.A1(new_n9), .A2(x[2]), .A3(new_n10), .ZN(new_n11));
  INV_X1   g04(.A(x[5]), .ZN(new_n12));
  AND2_X1  g05(.A1(x[1]), .A2(x[4]), .ZN(new_n13));
  AOI21_X1 g06(.A(new_n12), .B1(new_n13), .B2(new_n8), .ZN(new_n14));
  OAI21_X1 g07(.A(x[0]), .B1(x[2]), .B2(x[3]), .ZN(new_n15));
  NAND3_X1 g08(.A1(new_n11), .A2(new_n14), .A3(new_n15), .ZN(new_n16));
  NAND4_X1 g09(.A1(new_n8), .A2(x[1]), .A3(x[2]), .A4(x[4]), .ZN(new_n17));
  INV_X1   g10(.A(x[2]), .ZN(new_n18));
  NAND3_X1 g11(.A1(new_n18), .A2(x[0]), .A3(x[3]), .ZN(new_n19));
  INV_X1   g12(.A(x[1]), .ZN(new_n20));
  NAND2_X1 g13(.A1(new_n20), .A2(new_n12), .ZN(new_n21));
  OAI21_X1 g14(.A(new_n17), .B1(new_n19), .B2(new_n21), .ZN(new_n22));
  INV_X1   g15(.A(new_n22), .ZN(new_n23));
  NOR2_X1  g16(.A1(x[2]), .A2(x[3]), .ZN(new_n24));
  NOR2_X1  g17(.A1(x[4]), .A2(x[5]), .ZN(new_n25));
  OAI21_X1 g18(.A(new_n24), .B1(new_n25), .B2(x[1]), .ZN(new_n26));
  INV_X1   g19(.A(x[0]), .ZN(new_n27));
  OAI22_X1 g20(.A1(x[2]), .A2(x[3]), .B1(x[4]), .B2(x[5]), .ZN(new_n28));
  NAND3_X1 g21(.A1(new_n26), .A2(new_n27), .A3(new_n28), .ZN(new_n29));
  AOI21_X1 g22(.A(x[4]), .B1(new_n18), .B2(x[3]), .ZN(new_n30));
  NAND2_X1 g23(.A1(x[1]), .A2(x[5]), .ZN(new_n31));
  NAND2_X1 g24(.A1(new_n27), .A2(new_n8), .ZN(new_n32));
  NAND4_X1 g25(.A1(new_n30), .A2(new_n31), .A3(new_n21), .A4(new_n32), .ZN(new_n33));
  NAND4_X1 g26(.A1(new_n16), .A2(new_n23), .A3(new_n29), .A4(new_n33), .ZN(y0));
endmodule



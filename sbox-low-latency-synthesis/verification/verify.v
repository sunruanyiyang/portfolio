module tb_SB;

reg [5:0] x;
wire [5:0] y;

// 实例化你的S盒
SB uut(
    .x(x),
    .y(y)
);

// 赛题官方Dillon置换真值表（十六进制）
reg [5:0] truth_table[0:63];
initial begin
    truth_table[0] = 6'h00; truth_table[1] = 6'h36; truth_table[2] = 6'h30; truth_table[3] = 6'h0d;
    truth_table[4] = 6'h0f; truth_table[5] = 6'h12; truth_table[6] = 6'h35; truth_table[7] = 6'h23;
    truth_table[8] = 6'h19; truth_table[9] = 6'h3f; truth_table[10] = 6'h2d; truth_table[11] = 6'h34;
    truth_table[12] = 6'h03; truth_table[13] = 6'h14; truth_table[14] = 6'h29; truth_table[15] = 6'h21;
    truth_table[16] = 6'h3b; truth_table[17] = 6'h24; truth_table[18] = 6'h02; truth_table[19] = 6'h22;
    truth_table[20] = 6'h0a; truth_table[21] = 6'h08; truth_table[22] = 6'h39; truth_table[23] = 6'h25;
    truth_table[24] = 6'h3c; truth_table[25] = 6'h13; truth_table[26] = 6'h2a; truth_table[27] = 6'h0e;
    truth_table[28] = 6'h32; truth_table[29] = 6'h1a; truth_table[30] = 6'h3a; truth_table[31] = 6'h18;
    truth_table[32] = 6'h27; truth_table[33] = 6'h1b; truth_table[34] = 6'h15; truth_table[35] = 6'h11;
    truth_table[36] = 6'h10; truth_table[37] = 6'h1d; truth_table[38] = 6'h01; truth_table[39] = 6'h3e;
    truth_table[40] = 6'h2f; truth_table[41] = 6'h28; truth_table[42] = 6'h33; truth_table[43] = 6'h38;
    truth_table[44] = 6'h07; truth_table[45] = 6'h2b; truth_table[46] = 6'h2c; truth_table[47] = 6'h26;
    truth_table[48] = 6'h1f; truth_table[49] = 6'h0b; truth_table[50] = 6'h04; truth_table[51] = 6'h1c;
    truth_table[52] = 6'h3d; truth_table[53] = 6'h2e; truth_table[54] = 6'h05; truth_table[55] = 6'h31;
    truth_table[56] = 6'h09; truth_table[57] = 6'h06; truth_table[58] = 6'h17; truth_table[59] = 6'h20;
    truth_table[60] = 6'h1e; truth_table[61] = 6'h0c; truth_table[62] = 6'h37; truth_table[63] = 6'h16;
end

integer i;
integer error_count = 0;

initial begin
    $display("开始验证S盒功能...");
    $display("输入 | 输出 | 期望输出 | 结果");
    $display("--------------------------------");
    
    for (i = 0; i < 64; i = i + 1) begin
        x = i[5:0];
        #10;
        
        if (y !== truth_table[i]) begin
            $display("%2h   | %2h   | %2h       | ❌ 错误", x, y, truth_table[i]);
            error_count = error_count + 1;
        end else begin
            $display("%2h   | %2h   | %2h       | ✅ 正确", x, y, truth_table[i]);
        end
    end
    
    $display("--------------------------------");
    if (error_count == 0) begin
        $display("✅ 所有64个输入输出验证通过！功能完全正确");
    end else begin
        $display("❌ 发现 %0d 个错误", error_count);
    end
    
    $finish;
end

endmodule

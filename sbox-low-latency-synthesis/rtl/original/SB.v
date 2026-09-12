module SB(
    input  [5:0] x,
    output [5:0] y
);

wire x0=x[0];
wire x1=x[1];
wire x2=x[2];
wire x3=x[3];
wire x4=x[4];
wire x5=x[5];

//
// 二次项
//
wire x01 = x0 & x1;
wire x02 = x0 & x2;
wire x03 = x0 & x3;
wire x04 = x0 & x4;
wire x05 = x0 & x5;

wire x12 = x1 & x2;
wire x13 = x1 & x3;
wire x14 = x1 & x4;
wire x15 = x1 & x5;

wire x23 = x2 & x3;
wire x24 = x2 & x4;
wire x25 = x2 & x5;

wire x34 = x3 & x4;
wire x35 = x3 & x5;

wire x45 = x4 & x5;

//
// 三次项
//
wire x015 = x01 & x5;
wire x035 = x03 & x5;
wire x045 = x04 & x5;

wire x123 = x12 & x3;
wire x125 = x12 & x5;

wire x134 = x13 & x4;
wire x135 = x13 & x5;

wire x234 = x23 & x4;
wire x235 = x23 & x5;

wire x245 = x24 & x5;

wire x013 = x01 & x3;
wire x014 = x01 & x4;

wire x023 = x02 & x3;
wire x024 = x02 & x4;
wire x025 = x02 & x5;

wire x034 = x03 & x4;

wire x145 = x14 & x5;

//
// 四次项
//
wire x0124 = x01 & x24;
wire x0125 = x01 & x25;
wire x0123 = x01 & x23;

//
// y0
//
assign y[0] =
      x2 ^ x3 ^ x4 ^ x5
    ^ x01 ^ x02 ^ x04 ^ x14 ^ x23 ^ x35 ^ x45
    ^ x015 ^ x035 ^ x045 ^ x125 ^ x134 ^ x245
    ^ x0124;

//
// y1
//
assign y[1] =
      x0 ^ x2 ^ x4 ^ x5
    ^ x01 ^ x02 ^ x05 ^ x12 ^ x15 ^ x24 ^ x34 ^ x45
    ^ x015 ^ x023 ^ x024 ^ x025 ^ x035
    ^ x134 ^ x135 ^ x234 ^ x235 ^ x245
    ^ x0125;

//
// y2
//
assign y[2] =
      x0 ^ x2 ^ x5
    ^ x13 ^ x23 ^ x24 ^ x34
    ^ x013 ^ x014 ^ x024 ^ x123;

//
// y3
//
assign y[3] =
      x2 ^ x3 ^ x4
    ^ x01 ^ x02 ^ x04 ^ x05 ^ x12 ^ x14
    ^ x24 ^ x25 ^ x34
    ^ x023 ^ x025 ^ x035
    ^ x125 ^ x134 ^ x135
    ^ x234 ^ x235 ^ x245
    ^ x0125;

//
// y4
//
assign y[4] =
      x0 ^ x1 ^ x3 ^ x4
    ^ x03 ^ x23 ^ x24 ^ x25 ^ x34 ^ x35
    ^ x013 ^ x014 ^ x015
    ^ x023 ^ x024 ^ x025
    ^ x123;

//
// y5
//
assign y[5] =
      x0 ^ x1 ^ x4 ^ x5
    ^ x02 ^ x04 ^ x24 ^ x25
    ^ x013 ^ x014 ^ x015
    ^ x024 ^ x034 ^ x035
    ^ x125 ^ x134 ^ x135 ^ x145
    ^ x234 ^ x245
    ^ x0123 ^ x0124;

endmodule
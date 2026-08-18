#include <Wire.h>
#include "DFRobot_RGBLCD1602.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <math.h>
#include <HardwareSerial.h>

// ===================== 引脚定义 =====================
#define TDS_RX        32
#define TDS_TX        33
#define MSP20_AO      34
#define LIGHT_SENSOR  35

#define RGB_R         25
#define RGB_G         26
#define RGB_B         27

// ===================== 阈值定义 =====================
// 水质阈值 (TDS>600为差)
#define TDS_BAD_THRESHOLD   600
// 光线阈值 (模拟值<300为暗)
#define LIGHT_DARK_THRESHOLD 3000
// 压力阈值 (模拟值>2000为超标)
#define PRESSURE_HIGH_THRESHOLD 2000
// 波动/倾斜阈值 (对齐1.cpp逻辑)
#define SAMPLE_COUNT 10      
#define TILT_SAMPLE_COUNT 5
#define VAR_THRESHOLD_WAVE 0.1    // 波动剧烈阈值
#define TILT_THRESHOLD 20.0       // 倾斜过大阈值 (度)

// ===================== 设备初始化 =====================
const int initroll=-90;
DFRobot_RGBLCD1602 lcd(0x2D, 16, 2);
Adafruit_MPU6050 mpu;
HardwareSerial SerialTDS(2);

// ===================== TDS相关变量 =====================
unsigned char rdata[20];
unsigned int count2 = 0;
unsigned int ec = 0, getflag = 0, t = 0, ec1 = 0;
unsigned char getdata2;
int jishuflag = 0;

// ===================== 传感器数据变量 =====================
float temperature, pitch, roll;
int pressureValue, lightValue;
// 波动/倾斜检测变量
float accelX[SAMPLE_COUNT];
float accelY[SAMPLE_COUNT];
float tiltAnglesX[TILT_SAMPLE_COUNT];
float tiltAnglesY[TILT_SAMPLE_COUNT];

// ===================== RGB + LCD背光同步 =====================
void setRGB(int r, int g, int b) {
  analogWrite(RGB_R, r);
  analogWrite(RGB_G, g);
  analogWrite(RGB_B, b);
  lcd.setRGB(r, g, b);  // 背光完全同步
}

// ===================== 发送TDS查询指令 =====================
void getTDS() {
  SerialTDS.write(0xA0);
  SerialTDS.write(0x00);
  SerialTDS.write(0x00);
  SerialTDS.write(0x00);
  SerialTDS.write(0x00);
  SerialTDS.write(0xA0);
}


// ===================== 读取TDS（修复版，无serialEvent） =====================
void readTDS() {
  while (SerialTDS.available() > 0) {
    getdata2 = SerialTDS.read();
    rdata[count2] = getdata2;

    if (rdata[count2] == 0xAA) {
      count2 = 0;
      rdata[0] = 0xAA;
      count2++;
      getflag = 1;
    } else {
      if (count2 < 19) count2++;
    }
  }
}

// ===================== 波动/倾斜检测工具函数 =====================
// 计算方差
float calculateVariance(float *data, int count) {
  float sum = 0, mean = 0, variance = 0;
  for (int i = 0; i < count; i++) sum += data[i];
  mean = sum / count;
  for (int i = 0; i < count; i++) variance += sq(data[i] - mean);
  return variance / count;
}

// 计算数组平均值
float calculateMean(float *data, int count) {
  float sum = 0;
  for (int i = 0; i < count; i++) sum += data[i];
  return sum / count;
}

// 计算X/Y轴倾斜角 (度)
float getTiltAngleX(float ax, float ay, float az) {
  return atan2(ay, sqrt(ax*ax + az*az)) * RAD_TO_DEG;
}
float getTiltAngleY(float ax, float ay, float az) {
  return atan2(-ax, sqrt(ay*ay + az*az)) * RAD_TO_DEG;
}

// ===================== 波动/倾斜检测主函数 =====================
bool checkWaveAndTilt(String &errorMsg) {
  // 1. 采集加速度/倾斜数据
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    sensors_event_t a, g, tmp;
    mpu.getEvent(&a, &g, &tmp);
    float ax = a.acceleration.x;
    float ay = a.acceleration.y;
    float az = a.acceleration.z;
    
    accelX[i] = ax;
    accelY[i] = ay;
    
    // 采集倾斜角数据 (滑动窗口)
    if (i < TILT_SAMPLE_COUNT) {
      tiltAnglesX[i] = fabs(getTiltAngleX(ax, ay, az)); // 取绝对值
      tiltAnglesY[i] = fabs(getTiltAngleY(ax, ay, az));
    }
    delay(50);
  }
  
  // 2. 计算波动方差
  float varX = calculateVariance(accelX, SAMPLE_COUNT);
  float varY = calculateVariance(accelY, SAMPLE_COUNT);
  float totalVariance = varX + varY;
  
  // 3. 计算平均倾斜角 (初始roll补偿：原始roll为-90，需修正偏移)
  float avgTiltX = calculateMean(tiltAnglesX, TILT_SAMPLE_COUNT) - 90 - initroll;
  float avgTiltY = calculateMean(tiltAnglesY, TILT_SAMPLE_COUNT) - 90;
  
  // 4. 判断波动/倾斜异常
  bool isTooWavy = (totalVariance >= VAR_THRESHOLD_WAVE);
  bool isTooTilted = (abs(avgTiltX) >= TILT_THRESHOLD) || (abs(avgTiltY) >= TILT_THRESHOLD);
  Serial.printf("%.1f %.1f\n", avgTiltX, avgTiltY);
  
  if (isTooWavy) {
    errorMsg += "Too Wavy|";
  }
  if (isTooTilted) {
    errorMsg += "Too Tilted|";
  }
  
  return isTooWavy || isTooTilted;
}

// ===================== 综合状态检测 =====================
void checkAllStatus(String &mainMsg, String &subMsg, int &rgbR, int &rgbG, int &rgbB) {
  String errorMsg = "";
  bool isAbnormal = false;

  // 1. 水质检测 (TDS>600为差)
  if (ec > TDS_BAD_THRESHOLD) {
    errorMsg += "TDS Bad|";
    isAbnormal = true;
  }
  
  // 2. 光线检测 (模拟值<300为暗)
  if (lightValue > LIGHT_DARK_THRESHOLD) {
    errorMsg += "Too Dark|";
    isAbnormal = true;
  }
  
  // 3. 压力检测 (模拟值>2000为超标)
  /*if (pressureValue < PRESSURE_HIGH_THRESHOLD) {
    errorMsg += "Shallow Water|";
    isAbnormal = true;
  }*/
  
  // 4. 波动/倾斜检测
  bool waveTiltError = checkWaveAndTilt(errorMsg);
  if (waveTiltError) {
    isAbnormal = true;
  }

  // 5. 状态消息与颜色配置
  if (isAbnormal) {
    mainMsg = errorMsg;
    subMsg = "TDS:" + String(ec) + " Light:" + String(lightValue);
    rgbR = 100; rgbG = 0; rgbB = 0; // 红色：异常
  } else {
    mainMsg = "Environment fit: ";
    subMsg = "TDS:" + String(ec) + " Light:" + String(lightValue);
    rgbR = 0; rgbG = 100; rgbB = 0; // 绿色：正常
  }

  // 截断过长的异常信息（适配16字符LCD）
  if (mainMsg.length() > 16) {
    mainMsg = mainMsg.substring(0, 15) + "*";
  }
  if (subMsg.length() > 16) {
    subMsg = subMsg.substring(0, 15) + "*";
  }
}

// ===================== 初始化 =====================
void setup() {
  Serial.begin(115200);
  SerialTDS.begin(9600, SERIAL_8N1, TDS_RX, TDS_TX);

  pinMode(RGB_R, OUTPUT);
  pinMode(RGB_G, OUTPUT);
  pinMode(RGB_B, OUTPUT);
  setRGB(0, 60, 120); // 初始化蓝色

  lcd.init();
  lcd.clear();
  lcd.print("System Ready");
  delay(1500);

  // 初始化MPU6050
  if (!mpu.begin()) {
    lcd.clear();
    lcd.print("MPU6050 Error");
    while (1) delay(10);
  }
  mpu.setAccelerometerRange(MPU6050_RANGE_2_G); // 对齐1.cpp的2g量程
  mpu.setGyroRange(MPU6050_RANGE_250_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  delay(100);
}

// ===================== 主循环 =====================
void loop() {
  // 1. 发送查询并读取TDS
  getTDS();
  delay(800);
  readTDS();

  // 2. 解析TDS数据
  if (getflag == 1) {
    getflag = 0;
    jishuflag++;

    if (count2 >= 5) {
      // 温度解析
      t = (rdata[3] / 16) * 4096 + (rdata[3] % 16) * 256 + rdata[4];
      // 原始EC
      ec1 = (rdata[1] / 16) * 4096 + (rdata[1] % 16) * 256 + rdata[2];
      // 温度补偿
      if (t > 2500) {
        ec = (ec1 + (t - 2500) * 0.00011) / (1 + (t - 2500) * 0.000388);
      } else {
        ec = (ec1 - (2500 - t) * 0.00011) / (1 - (2500 - t) * 0.000388);
      }
    }
  }

  // 3. 读取其他传感器
  sensors_event_t a, g, tmp;
  mpu.getEvent(&a, &g, &tmp);
  temperature = tmp.temperature;
  pitch = atan2(a.acceleration.y, sqrt(a.acceleration.x*a.acceleration.x + a.acceleration.z*a.acceleration.z)) * RAD_TO_DEG;
  roll  = atan2(-a.acceleration.x, a.acceleration.z) * RAD_TO_DEG;

  pressureValue = analogRead(MSP20_AO);
  lightValue = analogRead(LIGHT_SENSOR);

  // 4. 检测所有状态并获取显示/颜色配置
  String mainMsg, subMsg;
  int rgbR, rgbG, rgbB;
  checkAllStatus(mainMsg, subMsg, rgbR, rgbG, rgbB);

  // 5. LCD显示更新
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print(mainMsg);
  lcd.setCursor(0, 1); lcd.print(subMsg);

  // 6. RGB背光/LED同步
  setRGB(rgbR, rgbG, rgbB);

  // 7. 串口输出调试
  Serial.printf("温度:%.1f°C TDS:%d 光感:%d 水压:%d Roll:%.1f°\n", 
                t/100.0, ec, lightValue, pressureValue, roll);
  Serial.printf("状态: %s | %s\n", mainMsg.c_str(), subMsg.c_str());

  delay(1000); // 主循环延迟，降低刷新率
}
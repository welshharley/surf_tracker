/*
 * CameraSideTracker — Heltec Wireless Tracker V2
 *
 * Receives surfer GNSS over LoRa, forwards to Pi as JSON over USB serial.
 * Receives motor commands from Pi, drives 3 stepper motors (base + mirrored
 * hinges) via DRV8825 drivers.
 *
 * Cores:
 *   Core 0 — motorTask: tight AccelStepper.run() loop, owns the steppers.
 *   Core 1 — Arduino loop(): LoRa RX, USB serial parsing, TFT updates.
 * Inter-core comms via FreeRTOS queue (commandQueue).
 *
 * Pi protocol (one command per line, terminated by \n):
 *   M <base_steps> <hinge_steps>   relative move; hinge applied to right, mirrored on left
 *   S                              status query (positions + counters as JSON)
 */

#include <RadioLib.h>
#include "HT_TinyGPS++.h"   // Heltec's bundled copy — DO NOT also include <TinyGPSPlus.h>
#include <HardwareSerial.h>
#include <AccelStepper.h>
#include "HT_st7735.h"

// ── LoRa pins (Heltec V2 internal — do not change) ──────────────────────────
#define LORA_CS    8
#define LORA_DIO1  14
#define LORA_RST   12
#define LORA_BUSY  13

// ── V2 power control ─────────────────────────────────────────────────────────
#define VEXT_CTRL  3   // GNSS + TFT power
#define PA_CSD     4   // PA shutdown (HIGH = enable)
#define PA_CTX     5   // PA TX path
#define VFEM_CTRL  7   // FEM power (required for RX)

// ── GNSS UART ───────────────────────────────────────────────────────────────
#define GNSS_RX    33
#define GNSS_TX    34
#define GNSS_RST   35

// ── Stepper driver pins (DRV8825) ───────────────────────────────────────────
// Picked to avoid every reserved pin on the V2 (LoRa SPI, PA/FEM, GNSS UART,
// TFT SPI on 38–42, Vext on 3, USB on 43/44). All 6 pins below are exposed
// on the J1/J2 headers and have no internal connection on this board.
//
// Wire on each DRV8825:
//   SLEEP + RESET → 3.3V
//   M0=GND, M1=GND, M2=3.3V    (1/16 microstep)
//   VMOT → motor PSU (12 V), with 100 µF cap across VMOT/GND
//   GND  → both Heltec GND and motor PSU GND (common ground)
#define BASE_STEP   21
#define BASE_DIR    48
#define HR_STEP     19
#define HR_DIR      20
#define HL_STEP     17
#define HL_DIR      18

// ── Tuning ──────────────────────────────────────────────────────────────────
#define GNSS_FIX_TIMEOUT_MS   60000
#define GNSS_MIN_SATS         3
#define GNSS_MAX_HDOP         3.0

#define MOTOR_MAX_SPEED      1600.0
#define MOTOR_ACCEL          1500.0

// ── Globals ─────────────────────────────────────────────────────────────────
SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
HT_st7735 display;
TinyGPSPlus gps; // this librayr is included and bundled with ht_tinygps (as aposed to just having the tinygps header)
HardwareSerial GPSSerial(1);

AccelStepper baseMotor      (AccelStepper::DRIVER, BASE_STEP, BASE_DIR);
AccelStepper hingeRightMotor(AccelStepper::DRIVER, HR_STEP,   HR_DIR);
AccelStepper hingeLeftMotor (AccelStepper::DRIVER, HL_STEP,   HL_DIR);

struct CameraPosition {
  bool   valid;
  double lat;
  double lon;
  float  alt;
  uint8_t sats;
  float  hdop;
};
CameraPosition cameraPos = {false, 0, 0, 0, 0, 0};

struct __attribute__((packed)) SurferGNSSPacket {
  uint32_t timestamp;
  int32_t  lat_e7;
  int32_t  lon_e7;
  int16_t  alt_dm;
  uint16_t speed_cms;
  uint16_t heading_cd;
  uint8_t  sats;
  uint8_t  hdop_x10;
};

// Inter-core message: relative motor move
struct MotorCommand {
  long base_delta;
  long hinge_delta;
};
QueueHandle_t commandQueue;

volatile bool packetReceived = false;
unsigned long lastHeartbeat = 0;
unsigned long packetCount = 0;
unsigned long commandCount = 0;

// ── ISR — must live in IRAM so it runs even during flash-cache stalls ───────
void IRAM_ATTR setRxFlag() {
  packetReceived = true;
}

// ── GNSS one-shot fix (blocking, only at startup) ───────────────────────────
void acquireCameraPosition() {
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4, 4, (String)"Acquiring GNSS", Font_7x10, ST7735_CYAN, ST7735_BLACK);
  Serial.println(F("Acquiring camera position..."));

  unsigned long start = millis();
  unsigned long lastUiUpdate = 0;

  while (millis() - start < GNSS_FIX_TIMEOUT_MS) {
    while (GPSSerial.available()) gps.encode(GPSSerial.read());

    if (gps.location.isValid() && gps.hdop.isValid() && gps.satellites.isValid()) {
      uint8_t sats = gps.satellites.value();
      float hdop = gps.hdop.hdop();
      if (sats >= GNSS_MIN_SATS && hdop > 0 && hdop <= GNSS_MAX_HDOP) {
        cameraPos.valid = true;
        cameraPos.lat   = gps.location.lat();
        cameraPos.lon   = gps.location.lng();
        cameraPos.alt   = gps.altitude.meters();
        cameraPos.sats  = sats;
        cameraPos.hdop  = hdop;
        Serial.printf("Camera fix: %.7f, %.7f, alt=%.1fm, sats=%d, hdop=%.2f\n",
                      cameraPos.lat, cameraPos.lon, cameraPos.alt,
                      cameraPos.sats, cameraPos.hdop);
        return;
      }
    }

    if (millis() - lastUiUpdate > 500) {
      lastUiUpdate = millis();
      uint8_t sats = gps.satellites.isValid() ? gps.satellites.value() : 0;
      float hdop = gps.hdop.isValid() ? gps.hdop.hdop() : 99.9;
      unsigned long elapsed = (millis() - start) / 1000;
      display.st7735_fill_screen(ST7735_BLACK);
      display.st7735_write_str(4,  4, (String)"Acquiring GNSS",         Font_7x10, ST7735_CYAN,   ST7735_BLACK);
      display.st7735_write_str(4, 18, "Sats: " + String(sats),          Font_7x10, ST7735_YELLOW, ST7735_BLACK);
      display.st7735_write_str(4, 30, "HDOP: " + String(hdop, 1),       Font_7x10, ST7735_YELLOW, ST7735_BLACK);
      display.st7735_write_str(4, 42, "Time: " + String(elapsed) + "s", Font_7x10, ST7735_WHITE,  ST7735_BLACK);
    }
  }

  Serial.println(F("GNSS fix TIMEOUT"));
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4, 4, (String)"GNSS Timeout", Font_7x10, ST7735_RED, ST7735_BLACK);
  delay(2000);
}

void showStatus(float lat, float lon, int sats, int16_t rssi,
                long basePos, long hingePos) {
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4,  4, (String)"Surfer Tracking",       Font_7x10, ST7735_CYAN,   ST7735_BLACK);
  display.st7735_write_str(4, 18, "Lat: "  + String(lat, 5),       Font_7x10, ST7735_GREEN,  ST7735_BLACK);
  display.st7735_write_str(4, 30, "Lon: "  + String(lon, 5),       Font_7x10, ST7735_GREEN,  ST7735_BLACK);
  display.st7735_write_str(4, 42, "Sat: "  + String(sats),         Font_7x10, ST7735_YELLOW, ST7735_BLACK);
  display.st7735_write_str(4, 54, "RSSI:" + String(rssi) + "dBm",  Font_7x10, ST7735_YELLOW, ST7735_BLACK);
  display.st7735_write_str(4, 70, "B:" + String(basePos),          Font_7x10, ST7735_WHITE,  ST7735_BLACK);
  display.st7735_write_str(4, 82, "H:" + String(hingePos),         Font_7x10, ST7735_WHITE,  ST7735_BLACK);
}

// ── Motor task (Core 0) ─────────────────────────────────────────────────────
// Owns the AccelStepper objects. Pulls commands from the queue, then runs a
// tight stepping loop. Yields only when all motors are idle so step pulse
// timing isn't disturbed during motion.
void motorTask(void* params) {
  baseMotor.setMaxSpeed(MOTOR_MAX_SPEED);
  baseMotor.setAcceleration(MOTOR_ACCEL);
  hingeRightMotor.setMaxSpeed(MOTOR_MAX_SPEED);
  hingeRightMotor.setAcceleration(MOTOR_ACCEL);
  hingeLeftMotor.setMaxSpeed(MOTOR_MAX_SPEED);
  hingeLeftMotor.setAcceleration(MOTOR_ACCEL);

  MotorCommand cmd;
  for (;;) {
    if (xQueueReceive(commandQueue, &cmd, 0) == pdTRUE) {
      baseMotor.move(cmd.base_delta);
      hingeRightMotor.move(cmd.hinge_delta);
      hingeLeftMotor.move(-cmd.hinge_delta);
    }

    baseMotor.run();
    hingeRightMotor.run();
    hingeLeftMotor.run();

    // if the watchdog timer assumes the task is hung itll sleep of 1ms
    if (baseMotor.distanceToGo() == 0 &&
        hingeRightMotor.distanceToGo() == 0 &&
        hingeLeftMotor.distanceToGo() == 0) {
      vTaskDelay(1);  // idle — yield to feed watchdog
    }
  }
}

// ── Pi command parser ───────────────────────────────────────────────────────
String cmdBuf = "";

void handlePiCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd.startsWith("M ")) {
    int s1 = cmd.indexOf(' ');
    int s2 = cmd.indexOf(' ', s1 + 1);
    if (s2 < 0) { Serial.println(F("{\"err\":\"bad M args\"}")); return; }
    long base = cmd.substring(s1 + 1, s2).toInt();
    long hinge = cmd.substring(s2 + 1).toInt();
    MotorCommand mc = { base, hinge };
    if (xQueueSend(commandQueue, &mc, 0) == pdTRUE) {
      commandCount++;
      Serial.printf("{\"ack\":\"M\",\"base\":%ld,\"hinge\":%ld}\n", base, hinge);
    } else {
      Serial.println(F("{\"err\":\"queue full\"}"));
    }
  }
  else if (cmd == "S") {
    Serial.printf("{\"status\":{\"base\":%ld,\"hingeR\":%ld,\"hingeL\":%ld,\"pkt\":%lu,\"cmd\":%lu}}\n",
                  baseMotor.currentPosition(),
                  hingeRightMotor.currentPosition(),
                  hingeLeftMotor.currentPosition(),
                  packetCount, commandCount);
  }
  else {
    Serial.printf("{\"err\":\"unknown: %s\"}\n", cmd.c_str());
  }
}

//this functions reads the serial and sedn the data to handlepicommand function
void readPiSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdBuf.length() > 0) {
        handlePiCommand(cmdBuf);
        cmdBuf = "";
      }
    } else {
      cmdBuf += c;
      if (cmdBuf.length() > 64) cmdBuf = "";  // overflow guard
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println(F("\n=== CameraSideTracker boot ==="));

  // V2 power-up ---- NEEDED FOR RELIABLE LORA TRANSMISSIONS
  pinMode(VEXT_CTRL, OUTPUT);
  pinMode(PA_CSD,    OUTPUT);
  pinMode(PA_CTX,    OUTPUT);
  pinMode(VFEM_CTRL, OUTPUT);
  digitalWrite(VEXT_CTRL, HIGH);
  digitalWrite(VFEM_CTRL, HIGH);
  digitalWrite(PA_CSD,    HIGH);
  digitalWrite(PA_CTX,    HIGH);
  delay(100);

  // TFT
  display.st7735_init();
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(10, 20, (String)"Booting...", Font_11x18, ST7735_GREEN, ST7735_BLACK);

  // GNSS one-shot fix, then park to save current
  pinMode(GNSS_RST, OUTPUT);
  digitalWrite(GNSS_RST, LOW); delay(10);
  digitalWrite(GNSS_RST, HIGH); delay(100);
  GPSSerial.begin(115200, SERIAL_8N1, GNSS_RX, GNSS_TX);
  acquireCameraPosition();
  while (cameraPos.valid == false){
    acquireCameraPosition();
  }
  GPSSerial.end();
  // digitalWrite(GNSS_RST, LOW);

  // Inter-core queue + motor task on Core 0
  // (Arduino loop() runs on Core 1 by default, so motorTask on Core 0 means
  // motors get a dedicated core with no contention from radio/serial work.)
  commandQueue = xQueueCreate(8, sizeof(MotorCommand));
  xTaskCreatePinnedToCore(
    motorTask,    // function
    "MotorTask",  // name (for debug)
    4096,         // stack bytes
    NULL,         // params
    2,            // priority — higher than Arduino loop's default 1
    NULL,         // task handle
    0             // pin to Core 0
  );

  // LoRa init
  Serial.println(F("Init SX1262..."));
  int state = radio.begin(915.0, 250.0, 7, 5, 0x34, 22, 8);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("LoRa init failed: %d\n", state);
    while (true) delay(1000);
  }
  radio.setPacketReceivedAction(setRxFlag);
  state = radio.startReceive();
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("startReceive failed: %d\n", state);
    while (true) delay(1000);
  }

  Serial.println(F("=== Ready ==="));
}

void loop() {
  // Heartbeat every 5s so the Pi knows the link is alive
  if (millis() - lastHeartbeat > 5000) {
    lastHeartbeat = millis();
    Serial.printf("{\"hb\":{\"up\":%lu,\"pkt\":%lu,\"cmd\":%lu}}\n",
                  millis() / 1000, packetCount, commandCount);
  }

  // LoRa packet → JSON to Pi → TFT update
  if (packetReceived) {
    packetReceived = false;
    packetCount++;

    SurferGNSSPacket pkt;
    int radioData = radio.readData((uint8_t*)&pkt, sizeof(pkt));
    if (radioData == RADIOLIB_ERR_NONE) {
      double surferLat = pkt.lat_e7 / 1e7;
      double surferLon = pkt.lon_e7 / 1e7;

      Serial.printf(
        "{\"ts\":%lu,"
        "\"surfer\":{\"lat\":%.7f,\"lon\":%.7f,\"alt\":%.1f,\"spd\":%.2f,\"hdg\":%.2f,\"sats\":%d,\"hdop\":%.1f},"
        "\"camera\":{\"valid\":%d,\"lat\":%.7f,\"lon\":%.7f,\"alt\":%.1f},"
        "\"link\":{\"rssi\":%.1f,\"snr\":%.2f}}\n",
        pkt.timestamp,
        surferLat, surferLon, pkt.alt_dm / 10.0,
        pkt.speed_cms / 100.0, pkt.heading_cd / 100.0,
        pkt.sats, pkt.hdop_x10 / 10.0,
        cameraPos.valid ? 1 : 0,
        cameraPos.lat, cameraPos.lon, cameraPos.alt,
        radio.getRSSI(), radio.getSNR()
      );

      showStatus(surferLat, surferLon, pkt.sats, radio.getRSSI(),
                 baseMotor.currentPosition(), hingeRightMotor.currentPosition());
    } else {
      Serial.printf("{\"err\":\"readData %d\"}\n", radioData);
    }
    radio.startReceive();
  }

  // Pi commands (non-blocking)
  readPiSerial();
}

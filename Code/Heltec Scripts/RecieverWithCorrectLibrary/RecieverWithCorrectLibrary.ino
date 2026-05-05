#include <RadioLib.h>
#include <TinyGPSPlus.h>
#include <HardwareSerial.h>
#include "HT_st7735.h"

// SX1262 pins for Heltec Wireless Tracker V2 (from schematic)
#define LORA_CS    8
#define LORA_DIO1  14
#define LORA_RST   12
#define LORA_BUSY  13

// V2-specific power control pins (from official schematic)
#define VEXT_CTRL  3   // Powers GNSS module and TFT
#define PA_CSD     4   // PA shutdown control - HIGH to enable PA
#define PA_CTX     5   // PA TX path enable
#define VFEM_CTRL  7   // Front-end module power enable - REQUIRED for RX too

// UC6580 GNSS UART pins
#define GNSS_RX    33
#define GNSS_TX    34
#define GNSS_RST   35   // GNSS reset, active low

// GNSS acquisition tuning
#define GNSS_FIX_TIMEOUT_MS   60000  // Give up after 2 minutes
#define GNSS_MIN_SATS         3       // Wait for at least this many sats
#define GNSS_MAX_HDOP         3.0     // Wait for HDOP below this

SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
HT_st7735 display;
TinyGPSPlus gps;
HardwareSerial GPSSerial(1);

// Camera position - captured once at startup, used forever after
struct CameraPosition {
  bool valid;
  double lat;
  double lon;
  float alt;
  uint8_t sats;
  float hdop;
};
CameraPosition cameraPos = {false, 0, 0, 0, 0, 0};

// Surfer packet structure (must match transmitter exactly)
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

volatile bool packetReceived = false;
unsigned long lastStatusPrint = 0;
unsigned long packetCount = 0;

void IRAM_ATTR setRxFlag() {
  packetReceived = true;
}

// Blocks until we get a good GNSS fix or timeout. Stores result in cameraPos.
// Updates the TFT with progress so the user knows what's happening.
void acquireCameraPosition() {
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4, 4, (String)"Acquiring GNSS", Font_7x10, ST7735_CYAN, ST7735_BLACK);
  Serial.println(F("Acquiring camera position..."));

  unsigned long start = millis();
  unsigned long lastUiUpdate = 0;

  while (millis() - start < GNSS_FIX_TIMEOUT_MS) {
    // Feed every available byte to the parser
    while (GPSSerial.available()) {
      gps.encode(GPSSerial.read());
    }

    // Check if we have a fix that meets our quality bar
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

    // UI update every 500ms while we wait
    if (millis() - lastUiUpdate > 500) {
      lastUiUpdate = millis();
      uint8_t sats = gps.satellites.isValid() ? gps.satellites.value() : 0;
      float hdop = gps.hdop.isValid() ? gps.hdop.hdop() : 99.9;
      unsigned long elapsed = (millis() - start) / 1000;
      
      display.st7735_fill_screen(ST7735_BLACK);
      display.st7735_write_str(4,  4, (String)"Acquiring GNSS",        Font_7x10, ST7735_CYAN,   ST7735_BLACK);
      display.st7735_write_str(4, 18, "Sats: " + String(sats),         Font_7x10, ST7735_YELLOW, ST7735_BLACK);
      display.st7735_write_str(4, 30, "HDOP: " + String(hdop, 1),      Font_7x10, ST7735_YELLOW, ST7735_BLACK);
      display.st7735_write_str(4, 42, "Time: " + String(elapsed) + "s", Font_7x10, ST7735_WHITE,  ST7735_BLACK);
      
      Serial.printf("...waiting: sats=%d hdop=%.2f t=%lus\n", sats, hdop, elapsed);
    }
  }

  Serial.println(F("GNSS fix TIMEOUT - continuing without camera position"));
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4, 4, (String)"GNSS Timeout", Font_7x10, ST7735_RED, ST7735_BLACK);
  delay(2000);
}

void showSurfer(float lat, float lon, float alt, float spd, int sats, int16_t rssi) {
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4,  4, (String)"Surfer Tracking",         Font_7x10, ST7735_CYAN,   ST7735_BLACK);
  display.st7735_write_str(4, 18, "Lat: " + String(lat, 5),          Font_7x10, ST7735_GREEN,  ST7735_BLACK);
  display.st7735_write_str(4, 30, "Lon: " + String(lon, 5),          Font_7x10, ST7735_GREEN,  ST7735_BLACK);
  display.st7735_write_str(4, 42, "Alt: " + String(alt, 1) + "m",    Font_7x10, ST7735_WHITE,  ST7735_BLACK);
  display.st7735_write_str(4, 54, "Spd: " + String(spd, 1) + "m/s",  Font_7x10, ST7735_WHITE,  ST7735_BLACK);
  display.st7735_write_str(4, 66, "Sat: " + String(sats),            Font_7x10, ST7735_YELLOW, ST7735_BLACK);
  display.st7735_write_str(4, 80, "RSSI:" + String(rssi) + "dBm",    Font_7x10, ST7735_YELLOW, ST7735_BLACK);
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println(F("\n=== RX Boot ==="));

  // ---- V2 power-up sequence ----
  // VEXT_CTRL HIGH powers GNSS *and* the TFT, so this single block handles both.
  pinMode(VEXT_CTRL, OUTPUT);
  pinMode(PA_CSD,    OUTPUT);
  pinMode(PA_CTX,    OUTPUT);
  pinMode(VFEM_CTRL, OUTPUT);

  digitalWrite(VEXT_CTRL, HIGH);  // Powers GNSS + TFT
  digitalWrite(VFEM_CTRL, HIGH);  // FEM - critical for RX
  digitalWrite(PA_CSD,    HIGH);  // Release PA from shutdown
  digitalWrite(PA_CTX,    HIGH);  // Enable TX path

  delay(100);

  // ---- TFT init ----
  display.st7735_init();
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(10, 20, (String)"Booting...", Font_11x18, ST7735_GREEN, ST7735_BLACK);

  // ---- GNSS init and one-shot fix ----
  pinMode(GNSS_RST, OUTPUT);
  digitalWrite(GNSS_RST, LOW);
  delay(10);
  digitalWrite(GNSS_RST, HIGH);
  delay(100);
  GPSSerial.begin(115200, SERIAL_8N1, GNSS_RX, GNSS_TX);

  acquireCameraPosition();
  // From here on, the GNSS is no longer needed. We could power it down to
  // save current, but the simplest thing is to just stop reading from it.

  // ---- LoRa init ----
  Serial.println(F("Initializing SX1262..."));
  int state = radio.begin(915.0, 250.0, 7, 5, 0x34, 22, 8);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print(F("INIT FAILED: "));
    Serial.println(state);
    while (true) delay(1000);
  }
  Serial.println(F("Radio init OK"));

  radio.setPacketReceivedAction(setRxFlag);
  state = radio.startReceive();
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print(F("startReceive failed: "));
    Serial.println(state);
    while (true) delay(1000);
  }
  Serial.println(F("=== Listening for packets ==="));
}

void loop() {
  // Heartbeat every 2s
  if (millis() - lastStatusPrint > 2000) {
    lastStatusPrint = millis();
    Serial.printf("[heartbeat] uptime=%lus, packets=%lu\n",
                  millis() / 1000, packetCount);
  }

  if (packetReceived) {
    packetReceived = false;
    packetCount++;

    SurferGNSSPacket pkt;
    int radioState = radio.readData((uint8_t*)&pkt, sizeof(pkt));

    if (radioState == RADIOLIB_ERR_NONE) {
      double surferLat = pkt.lat_e7 / 1e7;
      double surferLon = pkt.lon_e7 / 1e7;

      // JSON output for the Pi - includes both surfer and camera positions
      // so the Pi has everything it needs to compute pointing
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

      showSurfer(surferLat, surferLon, pkt.alt_dm / 10.0,
                 pkt.speed_cms / 100.0, pkt.sats, radio.getRSSI());
    } else {
      Serial.print(F("readData failed: "));
      Serial.println(radioState);
    }

    radio.startReceive();
  }
}



// #include <RadioLib.h>
// #include <TinyGPSPlus.h>
// #include "HT_st7735.h"

// // SX1262 pins for Heltec Wireless Tracker V2 (from schematic)
// #define LORA_CS    8
// #define LORA_DIO1  14
// #define LORA_RST   12
// #define LORA_BUSY  13

// // V2-specific power control pins (from official schematic)
// #define VEXT_CTRL  3   // Powers GNSS module and TFT (left on for symmetry)
// #define PA_CSD     4   // PA shutdown control - HIGH to enable PA
// #define PA_CTX     5   // PA TX path enable (only matters for TX, but harmless on RX)
// #define VFEM_CTRL  7   // Front-end module power enable - REQUIRED for RX too

// // UC6580 GNSS UART pins
// #define GNSS_RX    33
// #define GNSS_TX    34
// #define GNSS_RST   35   // GNSS reset, active low

// SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
// HT_st7735 display;
// TinyGPSPlus gps;

// struct MyGNSSPacket {
//   uint32_t timestamp;
//   int32_t  lat_e7;
//   int32_t  lon_e7;
//   int16_t  alt_dm;
//   uint8_t  sats;
//   uint8_t  hdop_x10;
// };

// struct __attribute__((packed))SurferGNSSPacket {
//   uint32_t timestamp;
//   int32_t  lat_e7;
//   int32_t  lon_e7;
//   int16_t  alt_dm;
//   uint16_t speed_cms;
//   uint16_t heading_cd;
//   uint8_t  sats;
//   uint8_t  hdop_x10;
// };

// bool GNSSChecked = false;
// volatile bool packetReceived = false;
// unsigned long lastStatusPrint = 0;
// unsigned long packetCount = 0;

// // Interrupt-driven RX - the ISR just sets a flag, real work happens in loop()
// // IRAM_ATTR forces the function into fast internal RAM so it can run during
// // flash-cache stalls without crashing the chip.
// void IRAM_ATTR setRxFlag() {
//   packetReceived = true;
// }

// void showGPS(float lat, float lon, float alt, float spd, int sats, int16_t rssi) {
//   display.st7735_fill_screen(ST7735_BLACK);
//   display.st7735_write_str(4,  4, (String)"GPS Receiver",            Font_7x10, ST7735_CYAN,   ST7735_BLACK);
//   display.st7735_write_str(4, 18, "Lat: " + String(lat, 5),          Font_7x10, ST7735_GREEN,  ST7735_BLACK);
//   display.st7735_write_str(4, 30, "Lon: " + String(lon, 5),          Font_7x10, ST7735_GREEN,  ST7735_BLACK);
//   display.st7735_write_str(4, 42, "Alt: " + String(alt, 1) + "m",    Font_7x10, ST7735_WHITE,  ST7735_BLACK);
//   display.st7735_write_str(4, 54, "Spd: " + String(spd, 1) + "km/h", Font_7x10, ST7735_WHITE,  ST7735_BLACK);
//   display.st7735_write_str(4, 66, "Sat: " + String(sats),            Font_7x10, ST7735_YELLOW, ST7735_BLACK);
//   display.st7735_write_str(4, 80, "RSSI:" + String(rssi) + "dBm",    Font_7x10, ST7735_YELLOW, ST7735_BLACK);
// }

// MyGNSSPacket myGNSS()


// void setup() {
//   Serial.begin(115200);
//   delay(2000);

//   Serial.println(F("\n=== RX Boot ==="));

//   // ---- V2 power-up sequence ----
//   // Without these, the front-end module is unpowered and no signal
//   // can reach the radio chip even if it's listening.
//   pinMode(VEXT_CTRL, OUTPUT);
//   pinMode(PA_CSD,    OUTPUT);
//   pinMode(PA_CTX,    OUTPUT);
//   pinMode(VFEM_CTRL, OUTPUT);

//   digitalWrite(VEXT_CTRL, HIGH);
//   digitalWrite(VFEM_CTRL, HIGH);  // Critical for RX - powers FEM
//   digitalWrite(PA_CSD,    HIGH);
//   digitalWrite(PA_CTX,    HIGH);

//   delay(100);

//     // ---- GNSS reset ----
//   pinMode(GNSS_RST, OUTPUT);
//   digitalWrite(GNSS_RST, LOW);
//   delay(10);
//   digitalWrite(GNSS_RST, HIGH);
//   delay(100);
//   GPSSerial.begin(115200, SERIAL_8N1, GNSS_RX, GNSS_TX);







//   // ---- LCD init ----
//   pinMode(Vext, OUTPUT);
//   digitalWrite(Vext, LOW);
//   delay(100);
//   display.st7735_init();
//   display.st7735_fill_screen(ST7735_BLACK);
//   display.st7735_write_str(10, 20, (String)"Hello!", 
//                           Font_11x18, ST7735_GREEN, ST7735_BLACK);
//   display.st7735_write_str(10, 50, (String)"Wireless Tracker", 
//                           Font_7x10, ST7735_WHITE, ST7735_BLACK);





//   // ---- LoRa init ----
//   // MUST match transmitter exactly - any mismatch and packets won't decode
//   Serial.println(F("Initializing SX1262..."));
//   int state = radio.begin(915.0, 250.0, 7, 5, 0x34, 22, 8);

//   Serial.print(F("radio.begin() returned: "));
//   Serial.println(state);

//   if (state != RADIOLIB_ERR_NONE) {
//     Serial.println(F("INIT FAILED - radio not responding"));
//     while (true) { delay(1000); Serial.print("."); }
//   }
//   Serial.println(F("Radio init OK"));

//   radio.setPacketReceivedAction(setRxFlag);

//   state = radio.startReceive();
//   Serial.print(F("startReceive() returned: "));
//   Serial.println(state);

//   if (state != RADIOLIB_ERR_NONE) {
//     Serial.println(F("RX MODE FAILED"));
//     while (true) { delay(1000); }
//   }

//   Serial.println(F("=== Listening for packets ==="));
// }

// void loop() {
//   // Heartbeat every 2s so we can see loop() is alive even if no packets arrive
//   if (millis() - lastStatusPrint > 2000) {
//     lastStatusPrint = millis();
//     Serial.printf("[heartbeat] uptime=%lus, packets=%lu, RSSI floor=%.1f dBm\n",
//                   millis() / 1000, packetCount, radio.getRSSI());
//   }
  
//   if (packetReceived) {
//     packetReceived = false;
//     packetCount++;

//     SurferGNSSPacket pkt;
//     int state = radio.readData((uint8_t*)&pkt, sizeof(pkt));

//     if (state == RADIOLIB_ERR_NONE) {
//       // Output as JSON line for easy parsing on the Pi.
//       // Pi just reads stdin from /dev/ttyUSB0 line by line.
//       Serial.printf(
//         "{\"ts\":%lu,\"lat\":%.7f,\"lon\":%.7f,\"alt\":%.1f,\"spd\":%.2f,\"hdg\":%.2f,\"sats\":%d,\"hdop\":%.1f,\"rssi\":%.1f,\"snr\":%.2f}\n",
//         pkt.timestamp,
//         pkt.lat_e7 / 1e7,
//         pkt.lon_e7 / 1e7,
//         pkt.alt_dm / 10.0,
//         pkt.speed_cms / 100.0,
//         pkt.heading_cd / 100.0,
//         pkt.sats,
//         pkt.hdop_x10 / 10.0,
//         radio.getRSSI(),
//         radio.getSNR()
//       );
//       showGPS(pkt.lat_e7/1e7, pkt.lon_e7/1e7, pkt.alt_dm/10.0, pkt.speed_cms/100.0, pkt.sats, radio.getRSSI());
//     } else {
//       Serial.print(F("readData failed: "));
//       Serial.println(state);
//     }

//     // Restart RX immediately - SX1262 drops out of receive after each packet
//     radio.startReceive();
//   }
// }




// #include <RadioLib.h>

// #define LORA_CS    8
// #define LORA_DIO1  14
// #define LORA_RST   12
// #define LORA_BUSY  13

// SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);

// struct __attribute__((packed)) GNSSPacket {
//   uint32_t timestamp;
//   int32_t  lat_e7;
//   int32_t  lon_e7;
//   int16_t  alt_dm;
//   uint16_t speed_cms;
//   uint16_t heading_cd;
//   uint8_t  sats;
//   uint8_t  hdop_x10;
// };

// volatile bool packetReceived = false;

// // Interrupt-driven RX - flag gets set when packet arrives, we handle in loop
// void IRAM_ATTR setRxFlag() {
//   packetReceived = true;
// }

// void setup() {
//   Serial.begin(115200);
//   delay(500);
  
//   // MUST match transmitter exactly
//   int state = radio.begin(915.0, 250.0, 7, 5, 0x34, 22, 8);
  
//   if (state != RADIOLIB_ERR_NONE) {
//     Serial.print(F("LoRa init failed: "));
//     Serial.println(state);
//     while (true) delay(1000);
//   }
  
//   radio.setPacketReceivedAction(setRxFlag);
  
//   state = radio.startReceive();
//   if (state != RADIOLIB_ERR_NONE) {
//     Serial.print(F("startReceive failed: "));
//     Serial.println(state);
//     while (true) delay(1000);
//   }
  
//   Serial.println(F("RX ready"));
// }

// void loop() {
//   if (packetReceived) {
//     packetReceived = false;
    
//     GNSSPacket pkt;
//     int state = radio.readData((uint8_t*)&pkt, sizeof(pkt));
    
//     if (state == RADIOLIB_ERR_NONE) {
//       // Output as JSON line for easy parsing on the Pi
//       // Pi just reads stdin from /dev/ttyUSB0 line by line
//       Serial.printf(
//         "{\"ts\":%lu,\"lat\":%.7f,\"lon\":%.7f,\"alt\":%.1f,\"spd\":%.2f,\"hdg\":%.2f,\"sats\":%d,\"hdop\":%.1f,\"rssi\":%.1f,\"snr\":%.2f}\n",
//         pkt.timestamp,
//         pkt.lat_e7 / 1e7,
//         pkt.lon_e7 / 1e7,
//         pkt.alt_dm / 10.0,
//         pkt.speed_cms / 100.0,
//         pkt.heading_cd / 100.0,
//         pkt.sats,
//         pkt.hdop_x10 / 10.0,
//         radio.getRSSI(),
//         radio.getSNR()
//       );
//     }
    
//     // Restart RX immediately - SX1262 drops out of receive mode after a packet
//     radio.startReceive();
//   }
// }
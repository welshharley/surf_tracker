#include <RadioLib.h>
#include <TinyGPSPlus.h>
#include <HardwareSerial.h>

// SX1262 pins for Heltec Wireless Tracker V2 (from schematic)
#define LORA_CS    8
#define LORA_DIO1  14
#define LORA_RST   12
#define LORA_BUSY  13

// V2-specific power control pins (from official schematic)
#define VEXT_CTRL  3   // Powers GNSS module and TFT
#define PA_CSD     4   // PA shutdown control - HIGH to enable PA
#define PA_CTX     5   // PA TX path enable
#define VFEM_CTRL  7   // Front-end module power enable

// UC6580 GNSS UART pins
#define GNSS_RX    33
#define GNSS_TX    34
#define GNSS_RST   35   // GNSS reset, active low

SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
TinyGPSPlus gps;
HardwareSerial GPSSerial(1);

// Packet structure - 20 bytes total, packed tight
// __attribute__((packed)) prevents the compiler from inserting padding bytes
struct __attribute__((packed)) GNSSPacket {
  uint32_t timestamp;   // 4 bytes - millis() since boot, for ordering
  int32_t  lat_e7;      // 4 bytes - latitude * 1e7 (gives ~1cm precision)
  int32_t  lon_e7;      // 4 bytes - longitude * 1e7
  int16_t  alt_dm;      // 2 bytes - altitude in decimeters
  uint16_t speed_cms;   // 2 bytes - speed in cm/s
  uint16_t heading_cd;  // 2 bytes - heading in centidegrees (0-35999)
  uint8_t  sats;        // 1 byte  - satellite count
  uint8_t  hdop_x10;    // 1 byte  - HDOP * 10 (quality indicator)
};

unsigned long lastSend = 0;
const unsigned long SEND_INTERVAL = 100; // 4 Hz

void setup() {
  Serial.begin(115200);
  delay(500);

  // ---- V2 power-up sequence ----
  // The V2 has a power amplifier (PA) and front-end module (FEM) that
  // must be enabled before the radio's RF path will work. Without this,
  // the SX1262 transmits but no signal reaches the antenna.
  pinMode(VEXT_CTRL, OUTPUT);
  pinMode(PA_CSD,    OUTPUT);
  pinMode(PA_CTX,    OUTPUT);
  pinMode(VFEM_CTRL, OUTPUT);

  digitalWrite(VEXT_CTRL, HIGH);  // Power on GNSS (and TFT)
  digitalWrite(VFEM_CTRL, HIGH);  // Power on the front-end module
  digitalWrite(PA_CSD,    HIGH);  // Release PA from shutdown
  digitalWrite(PA_CTX,    HIGH);  // Enable TX path through the PA

  delay(100);  // Let supplies stabilise

  // ---- GNSS reset ----
  pinMode(GNSS_RST, OUTPUT);
  digitalWrite(GNSS_RST, LOW);
  delay(10);
  digitalWrite(GNSS_RST, HIGH);
  delay(100);

  GPSSerial.begin(115200, SERIAL_8N1, GNSS_RX, GNSS_TX);

  // ---- LoRa init ----
  Serial.println(F("Starting LoRa..."));

  // Settings reasoning:
  // - 915.0 MHz: AU915 band (Australia)
  // - 250 kHz bandwidth: wider = faster but less sensitive. Good tradeoff for short range.
  // - SF7: lowest practical spreading factor. ~5kbps data rate, ~50ms airtime for our packet.
  //        Higher SF = more range but slower. SF7 still gets ~1-2km line of sight.
  // - CR 5 (4/5): minimal forward error correction. Fast, fine for clean RF environment.
  // - Sync word 0x34: distinguishes our network from random LoRa traffic.
  // - 22 dBm: max TX power for SX1262 itself (the V2's external PA boosts further).
  // - Preamble 8: standard, balances detection reliability vs airtime.
  int state = radio.begin(
    915.0,    // freq MHz
    250.0,    // bandwidth kHz
    7,        // spreading factor
    5,        // coding rate (4/5)
    0x34,     // sync word
    22,       // TX power dBm
    8         // preamble length
  );

  if (state != RADIOLIB_ERR_NONE) {
    Serial.print(F("LoRa init failed, code "));
    Serial.println(state);
    while (true) delay(1000);
  }

  Serial.println(F("LoRa ready"));
}

void loop() {
  // Continuously feed GPS parser
  while (GPSSerial.available()) {
    gps.encode(GPSSerial.read());
  }

  if (millis() - lastSend >= SEND_INTERVAL) {
    lastSend = millis();

    if (!gps.location.isValid()) {
      Serial.println(F("Waiting for GNSS fix..."));
      return;
    }

    GNSSPacket pkt;
    pkt.timestamp  = millis();
    pkt.lat_e7     = (int32_t)(gps.location.lat() * 1e7);
    pkt.lon_e7     = (int32_t)(gps.location.lng() * 1e7);
    pkt.alt_dm     = (int16_t)(gps.altitude.meters() * 10);
    pkt.speed_cms  = (uint16_t)(gps.speed.mps() * 100);
    pkt.heading_cd = (uint16_t)(gps.course.deg() * 100);
    pkt.sats       = gps.satellites.value();
    pkt.hdop_x10   = (uint8_t)(gps.hdop.hdop() * 10);

    int state = radio.transmit((uint8_t*)&pkt, sizeof(pkt));

    if (state == RADIOLIB_ERR_NONE) {
      Serial.printf("TX OK: %.6f, %.6f, sats=%d, hdop=%.1f, airtime=%lums\n",
        gps.location.lat(), gps.location.lng(),
        pkt.sats, pkt.hdop_x10 / 10.0,
        radio.getTimeOnAir(sizeof(pkt)) / 1000);
    } else {
      Serial.print(F("TX failed: "));
      Serial.println(state);
    }
  }
}



// #include <RadioLib.h>
// #include <TinyGPSPlus.h>
// #include <HardwareSerial.h>

// // SX1262 pins for Heltec Wireless Tracker V2
// #define LORA_CS    8
// #define LORA_DIO1  14
// #define LORA_RST   12
// #define LORA_BUSY  13

// // UC6580 GNSS pins
// #define GNSS_RX    33
// #define GNSS_TX    34
// #define GNSS_RST   35   // GNSS reset, active low
// #define VGNSS_CTRL 3    // Power control for GNSS

// SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
// TinyGPSPlus gps;
// HardwareSerial GPSSerial(1);

// // Packet structure - 20 bytes total, packed tight
// // Using a struct with __attribute__((packed)) prevents padding
// struct __attribute__((packed)) GNSSPacket {
//   uint32_t timestamp;   // 4 bytes - millis() since boot, for ordering
//   int32_t  lat_e7;      // 4 bytes - latitude * 1e7 (gives ~1cm precision)
//   int32_t  lon_e7;      // 4 bytes - longitude * 1e7
//   int16_t  alt_dm;      // 2 bytes - altitude in decimeters
//   uint16_t speed_cms;   // 2 bytes - speed in cm/s
//   uint16_t heading_cd;  // 2 bytes - heading in centidegrees (0-35999)
//   uint8_t  sats;        // 1 byte  - satellite count
//   uint8_t  hdop_x10;    // 1 byte  - HDOP * 10 (quality indicator)
// };

// unsigned long lastSend = 0;
// const unsigned long SEND_INTERVAL = 250; // 4 Hz

// void setup() {
//   Serial.begin(115200);
//   delay(500);
  
//   // Power on the GNSS module
//   pinMode(VGNSS_CTRL, OUTPUT);
//   digitalWrite(VGNSS_CTRL, HIGH);
  
//   pinMode(GNSS_RST, OUTPUT);
//   digitalWrite(GNSS_RST, LOW);
//   delay(10);
//   digitalWrite(GNSS_RST, HIGH);
//   delay(100);
  
//   GPSSerial.begin(115200, SERIAL_8N1, GNSS_RX, GNSS_TX);
  
//   Serial.println(F("Starting LoRa..."));
  
//   // Settings reasoning:
//   // - 915.0 MHz: AU915 band (Australia)
//   // - 250 kHz bandwidth: wider = faster but less sensitive. Good tradeoff for short range.
//   // - SF7: lowest practical spreading factor. ~5kbps data rate, ~50ms airtime for our packet.
//   //        Higher SF = more range but slower. SF7 still gets you ~1-2km line of sight.
//   // - CR 5 (4/5): minimal forward error correction. Fast, fine for clean RF environment.
//   // - Sync word 0x34: distinguishes our network from random LoRa traffic
//   // - 22 dBm: max TX power for SX1262 (~158mW). Boost legal in AU915.
//   // - Preamble 8: standard, balances detection reliability vs airtime
//   int state = radio.begin(
//     915.0,    // freq MHz
//     250.0,    // bandwidth kHz  
//     7,        // spreading factor
//     5,        // coding rate (4/5)
//     0x34,     // sync word
//     22,       // TX power dBm
//     8         // preamble length
//   );
  
//   if (state != RADIOLIB_ERR_NONE) {
//     Serial.print(F("LoRa init failed, code "));
//     Serial.println(state);
//     while (true) delay(1000);
//   }
  
//   Serial.println(F("LoRa ready"));
// }

// void loop() {
//   // Continuously feed GPS parser
//   while (GPSSerial.available()) {
//     gps.encode(GPSSerial.read());
//   }
  
//   if (millis() - lastSend >= SEND_INTERVAL) {
//     lastSend = millis();
    
//     if (!gps.location.isValid()) {
//       Serial.println(F("Waiting for GNSS fix..."));
//       return;
//     }
    
//     GNSSPacket pkt;
//     pkt.timestamp  = millis();
//     pkt.lat_e7     = (int32_t)(gps.location.lat() * 1e7);
//     pkt.lon_e7     = (int32_t)(gps.location.lng() * 1e7);
//     pkt.alt_dm     = (int16_t)(gps.altitude.meters() * 10);
//     pkt.speed_cms  = (uint16_t)(gps.speed.mps() * 100);
//     pkt.heading_cd = (uint16_t)(gps.course.deg() * 100);
//     pkt.sats       = gps.satellites.value();
//     pkt.hdop_x10   = (uint8_t)(gps.hdop.hdop() * 10);


    
//     int state = radio.transmit((uint8_t*)&pkt, sizeof(pkt));
    
//     if (state == RADIOLIB_ERR_NONE) {
//       Serial.printf("TX OK: %.6f, %.6f, sats=%d, hdop=%.1f\n",
//         gps.location.lat(), gps.location.lng(),
//         pkt.sats, pkt.hdop_x10 / 10.0);
//     } else {
//       Serial.print(F("TX failed: "));
//       Serial.println(state);
//     }
//   }
// }
/*
 * GPS_LoRa_Sender
 * Heltec Wireless Tracker V2
 *
 * Reads GPS (UC6580 via Serial1) and broadcasts position over LoRa.
 * Packet format: "LAT,LON,ALT,SPD,SAT"
 *
 * Required libraries:
 *   - TinyGPSPlus  (by Mikal Hart)
 *   - LoRaWan_APP.h + HT_st7735  (included in Heltec ESP32 board package)
 */

#include "LoRaWan_APP.h"
#include <TinyGPS++.h>
#include "HT_st7735.h"

// ── GPS pins (Heltec Wireless Tracker V2) ─────────────────────────────────────
#define GPS_RX_PIN  34    // MCU RX ← GPS TX
#define GPS_TX_PIN  33    // MCU TX → GPS RX
#define GPS_BAUD    9600
#define VGNSS_CTRL  3     // HIGH = GPS powered on

// ── LoRa settings ─────────────────────────────────────────────────────────────
#define RF_FREQUENCY            915000000   // Hz — change for your region
#define TX_OUTPUT_POWER         14          // dBm
#define LORA_BANDWIDTH          0           // 0=125kHz 1=250kHz 2=500kHz
#define LORA_SPREADING_FACTOR   9
#define LORA_CODINGRATE         1           // 1=4/5 2=4/6 3=4/7 4=4/8
#define LORA_PREAMBLE_LENGTH    8
#define LORA_FIX_LENGTH_PAYLOAD false
#define LORA_IQ_INVERSION       false

#define SEND_INTERVAL_MS  3000
#define BUFFER_SIZE       64

// ── Globals ───────────────────────────────────────────────────────────────────
char txpacket[BUFFER_SIZE];
bool lora_idle = true;

static RadioEvents_t RadioEvents;
TinyGPSPlus  gps;
HT_st7735    display;

// ── LoRa callbacks ────────────────────────────────────────────────────────────
void OnTxDone(void) {
  lora_idle = true;
}

void OnTxTimeout(void) {
  Radio.Sleep();
  lora_idle = true;
}

// ── Display helpers ───────────────────────────────────────────────────────────
void showStatus(String l1, String l2 = "", String l3 = "") {
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4, 4,  (String)"GPS Sender", Font_7x10, ST7735_CYAN,   ST7735_BLACK);
  display.st7735_write_str(4, 20, l1,                   Font_7x10, ST7735_WHITE,  ST7735_BLACK);
  if (l2.length()) display.st7735_write_str(4, 34, l2,  Font_7x10, ST7735_GREEN,  ST7735_BLACK);
  if (l3.length()) display.st7735_write_str(4, 48, l3,  Font_7x10, ST7735_YELLOW, ST7735_BLACK);
}

// ─────────────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);

  // Display
  pinMode(Vext, OUTPUT);
  digitalWrite(Vext, LOW);
  delay(100);
  display.st7735_init();
  showStatus("Booting...");

  // GPS
  pinMode(VGNSS_CTRL, OUTPUT);
  digitalWrite(VGNSS_CTRL, HIGH);
  delay(100);
  Serial1.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  Serial.println("GPS serial started");

  // LoRa
  RadioEvents.TxDone    = OnTxDone;
  RadioEvents.TxTimeout = OnTxTimeout;

  Radio.Init(&RadioEvents);
  Radio.SetChannel(RF_FREQUENCY);
  Radio.SetTxConfig(MODEM_LORA, TX_OUTPUT_POWER, 0, LORA_BANDWIDTH,
                    LORA_SPREADING_FACTOR, LORA_CODINGRATE,
                    LORA_PREAMBLE_LENGTH, LORA_FIX_LENGTH_PAYLOAD,
                    true, 0, 0, LORA_IQ_INVERSION, 3000);

  Serial.println("LoRa ready");
  showStatus("Waiting for GPS", "fix...");
}

unsigned long lastSendMs = 0;

void loop() {
  // Feed GPS parser
  while (Serial1.available()) {
    gps.encode(Serial1.read());
  }

  if (lora_idle && (millis() - lastSendMs >= SEND_INTERVAL_MS)) {
    lastSendMs = millis();

    if (!gps.location.isValid()) {
      Serial.println("No GPS fix");
      showStatus("No GPS fix", "Sats: " + String(gps.satellites.value()));
    } else {
      snprintf(txpacket, sizeof(txpacket), "%.6f,%.6f,%.1f,%.1f,%d",
               gps.location.lat(), gps.location.lng(),
               gps.altitude.meters(), gps.speed.kmph(),
               (int)gps.satellites.value());

      Serial.println("TX: " + String(txpacket));
      Radio.Send((uint8_t *)txpacket, strlen(txpacket));
      lora_idle = false;

      showStatus("TX OK",
                 "Lat:" + String(gps.location.lat(),  5),
                 "Lon:" + String(gps.location.lng(),  5));
    }
  }

  Radio.IrqProcess();
}

/*
 * GPS_LoRa_Receiver
 * Heltec Wireless Tracker V2
 *
 * Listens for GPS packets from the sender board and displays the
 * decoded position on the ST7735 screen.
 *
 * Packet format: "LAT,LON,ALT,SPD,SAT"
 *
 * Required libraries:
 *   - LoRaWan_APP.h + HT_st7735  (included in Heltec ESP32 board package)
 */

#include "LoRaWan_APP.h"
#include "HT_st7735.h"

// ── LoRa settings — must match sender exactly ─────────────────────────────────
#define RF_FREQUENCY            915000000
#define LORA_BANDWIDTH          0
#define LORA_SPREADING_FACTOR   9
#define LORA_CODINGRATE         1
#define LORA_PREAMBLE_LENGTH    8
#define LORA_SYMBOL_TIMEOUT     0
#define LORA_FIX_LENGTH_PAYLOAD false
#define LORA_IQ_INVERSION       false

#define BUFFER_SIZE  64

// ── Globals ───────────────────────────────────────────────────────────────────
char rxpacket[BUFFER_SIZE];

static RadioEvents_t RadioEvents;
HT_st7735 display;

// ── Display helpers ───────────────────────────────────────────────────────────
void showStatus(String l1, String l2 = "") {
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4, 4,  (String)"GPS Receiver", Font_7x10, ST7735_CYAN,  ST7735_BLACK);
  display.st7735_write_str(4, 20, l1,                     Font_7x10, ST7735_WHITE, ST7735_BLACK);
  if (l2.length()) display.st7735_write_str(4, 34, l2,    Font_7x10, ST7735_RED,   ST7735_BLACK);
}

void showGPS(float lat, float lon, float alt, float spd, int sats, int16_t rssi) {
  display.st7735_fill_screen(ST7735_BLACK);
  display.st7735_write_str(4,  4, (String)"GPS Receiver",            Font_7x10, ST7735_CYAN,   ST7735_BLACK);
  display.st7735_write_str(4, 18, "Lat: " + String(lat, 5),          Font_7x10, ST7735_GREEN,  ST7735_BLACK);
  display.st7735_write_str(4, 30, "Lon: " + String(lon, 5),          Font_7x10, ST7735_GREEN,  ST7735_BLACK);
  display.st7735_write_str(4, 42, "Alt: " + String(alt, 1) + "m",    Font_7x10, ST7735_WHITE,  ST7735_BLACK);
  display.st7735_write_str(4, 54, "Spd: " + String(spd, 1) + "km/h", Font_7x10, ST7735_WHITE,  ST7735_BLACK);
  display.st7735_write_str(4, 66, "Sat: " + String(sats),            Font_7x10, ST7735_YELLOW, ST7735_BLACK);
  display.st7735_write_str(4, 80, "RSSI:" + String(rssi) + "dBm",    Font_7x10, ST7735_YELLOW, ST7735_BLACK);
}

// ── LoRa callbacks ────────────────────────────────────────────────────────────
void OnRxDone(uint8_t *payload, uint16_t size, int16_t rssi, int8_t snr) {
  int len = min((int)size, BUFFER_SIZE - 1);
  memcpy(rxpacket, payload, len);
  rxpacket[len] = '\0';

  Serial.printf("RX [RSSI %d dBm / SNR %d dB]: %s\n", rssi, snr, rxpacket);

  float lat, lon, alt, spd;
  int   sats;
  int matched = sscanf(rxpacket, "%f,%f,%f,%f,%d", &lat, &lon, &alt, &spd, &sats);

  if (matched == 5) {
    showGPS(lat, lon, alt, spd, sats, rssi);
  } else {
    showStatus("Bad packet:", String(rxpacket).substring(0, 20));
  }

  // Return to receive mode
  Radio.Rx(0);
}

void OnRxTimeout(void) {
  Radio.Rx(0);
}

void OnRxError(void) {
  Radio.Rx(0);
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

  // LoRa
  RadioEvents.RxDone    = OnRxDone;
  RadioEvents.RxTimeout = OnRxTimeout;
  RadioEvents.RxError   = OnRxError;

  Radio.Init(&RadioEvents);
  Radio.SetChannel(RF_FREQUENCY);
  Radio.SetRxConfig(MODEM_LORA, LORA_BANDWIDTH, LORA_SPREADING_FACTOR,
                    LORA_CODINGRATE, 0, LORA_PREAMBLE_LENGTH,
                    LORA_SYMBOL_TIMEOUT, LORA_FIX_LENGTH_PAYLOAD,
                    0, true, 0, 0, LORA_IQ_INVERSION, true);

  Radio.Rx(0);  // start continuous receive
  Serial.println("Listening for GPS packets...");
  showStatus("Listening...");
}

void loop() {
  Radio.IrqProcess();
}

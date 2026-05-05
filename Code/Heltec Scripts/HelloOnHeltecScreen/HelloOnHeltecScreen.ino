#include "HT_st7735.h"

HT_st7735 st7735;

void setup() {
  Serial.begin(115200);
  
  // Power on the Vext rail that feeds the display
  pinMode(Vext, OUTPUT);
  digitalWrite(Vext, LOW);
  delay(100);
  
  st7735.st7735_init();
  st7735.st7735_fill_screen(ST7735_BLACK);
  
  st7735.st7735_write_str(10, 20, (String)"Hello!", 
                          Font_11x18, ST7735_GREEN, ST7735_BLACK);
  st7735.st7735_write_str(10, 50, (String)"Wireless Tracker", 
                          Font_7x10, ST7735_WHITE, ST7735_BLACK);
}

void loop() {
  Serial.println("Running...");
  delay(1000);
}
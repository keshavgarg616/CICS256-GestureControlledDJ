#include <Arduino.h>

#define POT1_PIN 36
#define POT2_PIN 39

void setup()
{
    Serial.begin(115200);

    // Initialize ADC pins (optional for ESP32 analogRead, but good practice)
    pinMode(POT1_PIN, INPUT);
    pinMode(POT2_PIN, INPUT);
}

void loop()
{
    // Read both potentiometers
    int pot1 = analogRead(POT1_PIN);
    int pot2 = analogRead(POT2_PIN);

    // Print values in a format supported by the Arduino Serial Plotter
    // Format: "Label1:Value1,Label2:Value2"
    Serial.print("Pot1:");
    Serial.print(pot1);
    Serial.print(",");
    Serial.print("Pot2:");
    Serial.println(pot2);

    // Small delay to make the plotter easier to read
    delay(50);
}
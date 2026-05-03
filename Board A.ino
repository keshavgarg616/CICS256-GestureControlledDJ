#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <FastLED.h>
#include <ESP32Servo.h>
#include "Gesture.h"

// --- NeoPixel Config ---
#define STRIP_PIN 25
#define RING1_PIN 12
#define RING2_PIN 26 // Moved to 26 to free up Touch Pin 14
#define NUM_STRIP_LEDS 30
#define NUM_RING_LEDS 16
CRGB stripLeds[NUM_STRIP_LEDS];
CRGB ring1Leds[NUM_RING_LEDS];
CRGB ring2Leds[NUM_RING_LEDS];

// --- Hardware Config ---
#define POT1_PIN 36
#define POT2_PIN 39
#define SERVO_PIN 18
#define BUTTON_PIN 5

// Now 7 Piano Keys
const int NUM_PIANO_KEYS = 7;
const int PIANO_PINS[NUM_PIANO_KEYS] = {4, 13, 15, 27, 32, 33, 14}; // Added 14

Servo myServo;
Adafruit_SSD1306 display(128, 64, &Wire, -1);
paj7620 Gesture;

// Store state for the OLED display
String latestUltrasonicData = "Waiting...";
String lastGesture = "None";
String lastPianoKey = "None";

void setup()
{
  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, 16, 17); // Link to ESP32 B

  // 1. Init Servo & Button
  myServo.attach(SERVO_PIN);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // 2. Init LEDs
  FastLED.addLeds<WS2812B, STRIP_PIN, GRB>(stripLeds, NUM_STRIP_LEDS);
  FastLED.addLeds<WS2812B, RING1_PIN, GRB>(ring1Leds, NUM_RING_LEDS);
  FastLED.addLeds<WS2812B, RING2_PIN, GRB>(ring2Leds, NUM_RING_LEDS);
  FastLED.clear();
  FastLED.show();

  // 3. Init I2C (OLED & Gesture)
  Wire.begin(21, 22);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C))
  {
    Serial.println("OLED init failed!");
  }
  display.clearDisplay();
  display.setTextSize(1);
  // display.setRotation(2); // Upside down
  display.setTextColor(WHITE);
  display.setCursor(0, 0);
  display.println("System Booting...");
  display.display();

  // 4. Init Gesture Sensor
  if (!Gesture.init())
  {
    Serial.println("Gesture sensor init failed!");
    display.println("Gesture: FAILED");
  }
  else
  {
    Serial.println("Gesture sensor ready.");
    display.println("Gesture: OK");
  }
  display.display();
  delay(1000);
}

void loop()
{
  // --- A. Read UART from ESP32 B (Ultrasonics) ---
  if (Serial2.available())
  {
    latestUltrasonicData = Serial2.readStringUntil('\n');
    Serial.println("Ultrasonics: " + latestUltrasonicData);
  }

  // --- B. Read Analog Inputs & Actuate ---
  int pot1 = analogRead(POT1_PIN);
  int pot2 = analogRead(POT2_PIN);

  int servoAngle = map(pot1, 0, 4095, 0, 180);
  myServo.write(servoAngle);

  int ledBrightness = map(pot2, 0, 4095, 0, 255);
  FastLED.setBrightness(ledBrightness);

  // Update all 3 NeoPixel strands
  uint8_t colorIndex = (millis() / 1000) % 3;
  CRGB testColor = (colorIndex == 0) ? CRGB::Red : (colorIndex == 1) ? CRGB::Green
                                                                     : CRGB::Blue;
  fill_solid(stripLeds, NUM_STRIP_LEDS, testColor);
  fill_solid(ring1Leds, NUM_RING_LEDS, testColor);
  fill_solid(ring2Leds, NUM_RING_LEDS, testColor);
  FastLED.show();

  // --- C. Read Digital Button ---
  bool buttonPressed = (digitalRead(BUTTON_PIN) == LOW);

  // --- D. Read 7 Touch Piano Keys ---
  for (int i = 0; i < NUM_PIANO_KEYS; i++)
  {
    if (touchRead(PIANO_PINS[i]) < 30)
    {
      lastPianoKey = String(i + 1);
    }
  }

  // --- E. Read All 9 Gestures ---
  paj7620_gesture_t result;
  if (Gesture.getResult(result))
  {
    switch (result)
    {
    case UP:
      lastGesture = "Up";
      break;
    case DOWN:
      lastGesture = "Down";
      break;
    case LEFT:
      lastGesture = "Left";
      break;
    case RIGHT:
      lastGesture = "Right";
      break;
    case PUSH:
      lastGesture = "Forward";
      break;
    case POLL:
      lastGesture = "Backward";
      break;
    case CLOCKWISE:
      lastGesture = "Clockwise";
      break;
    case ANTI_CLOCKWISE:
      lastGesture = "Counter-Clockwise";
      break;
    case WAVE:
      lastGesture = "Wave";
      break;
    default:
      lastGesture = "Unknown";
      break;
    }
    Serial.println("Gesture Detected: " + lastGesture);
  }

  // --- F. Update OLED Dashboard ---
  display.clearDisplay();

  // Section 1: Ultrasonic Payload
  display.setCursor(0, 0);
  display.println("- Sensors (cm) -");
  display.println(latestUltrasonicData);

  // Section 2: Hardware States
  display.println();
  display.printf("Srv:%d | LED:%d\n", servoAngle, ledBrightness);
  display.printf("Btn:%s | Key:%s\n", buttonPressed ? "ON " : "OFF", lastPianoKey.c_str());

  // Section 3: Gesture
  display.println();
  display.println("Last Gesture:");
  display.setTextSize(2);
  display.println(lastGesture);
  display.setTextSize(1);

  display.display();

  delay(50);
}
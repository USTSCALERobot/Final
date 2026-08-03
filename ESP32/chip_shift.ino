/*
    Ryan Bercich
    University of St. Thomas
    30 July 2026
    chip_shift.ino

    ***NOTE this file is intended to be compiled with the Arduino IDE for an
    ESP32-S3 Sense camera board. It is here for reference only.***

  ESP32-CAM port of chip_shift.py

  Default hardware: ESP32-S3 Sense with OV2640 camera.

  Serial commands:
    c  Save the current chip center as the reference position
    r  Erase a live calibration and restore the standard-chip reference

  Image coordinates increase downward. A positive shift therefore means that
  the detected chip is lower in the image than the saved reference.
*/

#include "esp_camera.h"
#include <Preferences.h>
#include <WiFi.h>
#include <WebServer.h>

// ESP32-S3 Sense camera pins. These match the verified JPEG-streaming sketch.
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  10
#define SIOD_GPIO_NUM  40
#define SIOC_GPIO_NUM  39
#define Y9_GPIO_NUM    48
#define Y8_GPIO_NUM    11
#define Y7_GPIO_NUM    12
#define Y6_GPIO_NUM    14
#define Y5_GPIO_NUM    16
#define Y4_GPIO_NUM    18
#define Y3_GPIO_NUM    17
#define Y2_GPIO_NUM    15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM  47
#define PCLK_GPIO_NUM  13

// Same ROI used by chip_shift.py for a 320 x 240 image.
constexpr int ROI_X = 130;
// The held chip is centered near row 161 at the arm's inspection pose. Limit
// the search to that region so objects passing through during pickup are not
// mistaken for the held chip.
constexpr int ROI_Y = 90;
constexpr int ROI_W = 40;
constexpr int ROI_H = 140;

constexpr float MIN_ROW_OCCUPANCY = 0.60f;
// On-demand capture already limits detection to the post-pick inspection
// moment. Keep only a modest minimum so exposure changes do not fragment the
// chip into a run that is rejected.
constexpr int MIN_RUN_LENGTH = 18;
constexpr unsigned long WIFI_RECONNECT_INTERVAL_MS = 1000;

// The Pi broadcasts this hotspot from its Wi-Fi adapter. The ESP joins it at
// a fixed address, allowing the Pi to read http://10.42.0.20/shift.
constexpr char WIFI_SSID[] = "espsignal";
constexpr char WIFI_PASSWORD[] = "scaleuser123";
const IPAddress ESP_ADDRESS(10, 42, 0, 20);
const IPAddress PI_GATEWAY(10, 42, 0, 1);
const IPAddress SUBNET_MASK(255, 255, 255, 0);

// Reference measured from the standard held-chip image using the same camera
// orientation: detected rows 133..189, centered at 161 px.
constexpr float STANDARD_CHIP_CENTER = 161.0f;

Preferences preferences;
WebServer server(80);
float referenceCenter = STANDARD_CHIP_CENTER;
float latestCenter = NAN;
float latestConfidence = 0.0f;
uint8_t latestThreshold = 0;
bool latestDetectionValid = false;

// Buffers hold only the ROI, not another full camera frame.
uint8_t blurredROI[ROI_W * ROI_H];
bool occupiedRows[ROI_H];

uint8_t pixelAtClamped(
    const uint8_t *frame, int frameWidth, int frameHeight, int x, int y) {
  x = constrain(x, 0, frameWidth - 1);
  y = constrain(y, 0, frameHeight - 1);
  return frame[y * frameWidth + x];
}

void blurROI5x5(
    const uint8_t *frame, int frameWidth, int frameHeight) {
  // Separable 5-tap Gaussian weights [1 4 6 4 1], applied directly.
  constexpr int weights[5] = {1, 4, 6, 4, 1};

  for (int ry = 0; ry < ROI_H; ++ry) {
    for (int rx = 0; rx < ROI_W; ++rx) {
      int weightedSum = 0;
      int totalWeight = 0;

      for (int ky = -2; ky <= 2; ++ky) {
        for (int kx = -2; kx <= 2; ++kx) {
          const int weight = weights[ky + 2] * weights[kx + 2];
          weightedSum += weight * pixelAtClamped(
              frame, frameWidth, frameHeight,
              ROI_X + rx + kx, ROI_Y + ry + ky);
          totalWeight += weight;
        }
      }

      blurredROI[ry * ROI_W + rx] = weightedSum / totalWeight;
    }
  }
}

uint8_t otsuThreshold() {
  uint32_t histogram[256] = {};
  constexpr int pixelCount = ROI_W * ROI_H;

  for (int i = 0; i < pixelCount; ++i) {
    ++histogram[blurredROI[i]];
  }

  uint64_t totalIntensity = 0;
  for (int level = 0; level < 256; ++level) {
    totalIntensity += static_cast<uint64_t>(level) * histogram[level];
  }

  uint32_t backgroundCount = 0;
  uint64_t backgroundIntensity = 0;
  double bestVariance = -1.0;
  uint8_t bestThreshold = 0;

  for (int level = 0; level < 256; ++level) {
    backgroundCount += histogram[level];
    if (backgroundCount == 0) {
      continue;
    }

    const uint32_t foregroundCount = pixelCount - backgroundCount;
    if (foregroundCount == 0) {
      break;
    }

    backgroundIntensity += static_cast<uint64_t>(level) * histogram[level];
    const double backgroundMean =
        static_cast<double>(backgroundIntensity) / backgroundCount;
    const double foregroundMean =
        static_cast<double>(totalIntensity - backgroundIntensity) /
        foregroundCount;
    const double difference = backgroundMean - foregroundMean;
    const double variance =
        static_cast<double>(backgroundCount) * foregroundCount *
        difference * difference;

    if (variance > bestVariance) {
      bestVariance = variance;
      bestThreshold = level;
    }
  }

  return bestThreshold;
}

bool detectChip(
    const uint8_t *frame, int frameWidth, int frameHeight,
    float &centerY, float &confidence, uint8_t &threshold) {
  if (ROI_X < 0 || ROI_Y < 0 ||
      ROI_X + ROI_W > frameWidth || ROI_Y + ROI_H > frameHeight) {
    Serial.println("ERROR: ROI lies outside the camera frame.");
    return false;
  }

  blurROI5x5(frame, frameWidth, frameHeight);
  threshold = otsuThreshold();

  for (int row = 0; row < ROI_H; ++row) {
    int darkCount = 0;
    for (int column = 0; column < ROI_W; ++column) {
      if (blurredROI[row * ROI_W + column] <= threshold) {
        ++darkCount;
      }
    }
    occupiedRows[row] =
        darkCount >= static_cast<int>(ROI_W * MIN_ROW_OCCUPANCY);
  }

  int bestStart = -1;
  int bestEnd = -1;
  float bestReferenceDistance = INFINITY;
  int row = 0;

  while (row < ROI_H) {
    while (row < ROI_H && !occupiedRows[row]) {
      ++row;
    }
    const int start = row;
    while (row < ROI_H && occupiedRows[row]) {
      ++row;
    }
    const int end = row - 1;

    if (start < ROI_H) {
      const int runLength = end - start + 1;
      if (runLength >= MIN_RUN_LENGTH) {
        const float candidateCenter =
            ROI_Y + (start + end) / 2.0f;
        const float referenceDistance =
            fabsf(candidateCenter - referenceCenter);
        if (bestStart < 0 || referenceDistance < bestReferenceDistance ||
            (referenceDistance == bestReferenceDistance &&
             runLength > bestEnd - bestStart + 1)) {
          bestStart = start;
          bestEnd = end;
          bestReferenceDistance = referenceDistance;
        }
      }
    }
  }

  if (bestStart < 0) {
    return false;
  }

  int darkPixels = 0;
  const int rowsInChip = bestEnd - bestStart + 1;
  for (int y = bestStart; y <= bestEnd; ++y) {
    for (int x = 0; x < ROI_W; ++x) {
      if (blurredROI[y * ROI_W + x] <= threshold) {
        ++darkPixels;
      }
    }
  }

  centerY = ROI_Y + (bestStart + bestEnd) / 2.0f;
  confidence =
      static_cast<float>(darkPixels) / (rowsInChip * ROI_W);
  return true;
}

bool initializeCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_GRAYSCALE;
  config.frame_size = FRAMESIZE_QVGA;  // 320 x 240
  config.jpeg_quality = 12;            // Ignored for grayscale
  config.fb_count = 1;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location =
      psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

  const esp_err_t result = esp_camera_init(&config);
  if (result != ESP_OK) {
    Serial.printf("Camera initialization failed: 0x%x\n", result);
    return false;
  }

  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor == nullptr) {
    Serial.println("Camera sensor handle is null after initialization.");
    esp_camera_deinit();
    return false;
  }
  sensor->set_vflip(sensor, 1);
  sensor->set_hmirror(sensor, 0);

  return true;
}

bool captureAndDetectChip() {
  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    latestCenter = NAN;
    latestDetectionValid = false;
    Serial.println("ERROR: Camera capture failed.");
    return false;
  }

  float confidence = 0.0f;
  uint8_t threshold = 0;
  const bool found = frame->format == PIXFORMAT_GRAYSCALE &&
      detectChip(
          frame->buf, frame->width, frame->height,
          latestCenter, confidence, threshold);

  esp_camera_fb_return(frame);

  if (!found) {
    latestCenter = NAN;
    latestDetectionValid = false;
    Serial.println("No chip found in requested frame.");
    return false;
  }

  latestConfidence = confidence;
  latestThreshold = threshold;
  latestDetectionValid = true;

  const float shift = latestCenter - referenceCenter;
  Serial.printf(
      "center=%.1f px, confidence=%.0f%%, threshold=%u, shift=%.1f px\n",
      latestCenter, confidence * 100.0f, threshold, shift);
  return true;
}

void sendShiftResponse() {
  // Capture on demand. The Pi requests this endpoint only after the arm has
  // picked up the chip, reached its inspection pose, and settled.
  captureAndDetectChip();
  if (!latestDetectionValid || isnan(latestCenter)) {
    server.send(
        503, "application/json",
        "{\"ok\":false,\"error\":\"no chip detected\"}");
    return;
  }

  const float shift = latestCenter - referenceCenter;
  char response[192];
  snprintf(
      response, sizeof(response),
      "{\"ok\":true,\"center_px\":%.1f,\"reference_px\":%.1f,"
      "\"shift_px\":%.1f,\"confidence\":%.3f,\"threshold\":%u}",
      latestCenter, referenceCenter, shift, latestConfidence,
      latestThreshold);
  server.send(200, "application/json", response);
}

void calibrateFromCurrentDetection() {
  // Calibration is also an explicit measurement request, so use a fresh frame
  // rather than requiring a preceding /shift call.
  captureAndDetectChip();
  if (!latestDetectionValid || isnan(latestCenter)) {
    server.send(
        409, "application/json",
        "{\"ok\":false,\"error\":\"no chip detected\"}");
    return;
  }
  referenceCenter = latestCenter;
  preferences.putFloat("refCenter", referenceCenter);
  char response[96];
  snprintf(
      response, sizeof(response),
      "{\"ok\":true,\"reference_px\":%.1f}", referenceCenter);
  server.send(200, "application/json", response);
}

void restoreStandardReference() {
  preferences.remove("refCenter");
  referenceCenter = STANDARD_CHIP_CENTER;
  char response[96];
  snprintf(
      response, sizeof(response),
      "{\"ok\":true,\"reference_px\":%.1f}", referenceCenter);
  server.send(200, "application/json", response);
}

void sendDebugFrame() {
  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    server.send(
        503, "application/json",
        "{\"ok\":false,\"error\":\"camera capture failed\"}");
    return;
  }

  if (frame->format != PIXFORMAT_GRAYSCALE) {
    esp_camera_fb_return(frame);
    server.send(
        500, "application/json",
        "{\"ok\":false,\"error\":\"camera frame is not grayscale\"}");
    return;
  }

  // PGM is a simple viewable grayscale format: an ASCII header followed by
  // the camera's raw 8-bit pixels. It lets us inspect the exact detector input.
  char header[48];
  const int headerLength = snprintf(
      header, sizeof(header), "P5\n%u %u\n255\n", frame->width, frame->height);
  server.sendHeader(
      "Content-Disposition", "attachment; filename=esp-debug-frame.pgm");
  server.setContentLength(headerLength + frame->len);
  server.send(200, "image/x-portable-graymap", "");

  WiFiClient responseClient = server.client();
  responseClient.write(
      reinterpret_cast<const uint8_t *>(header), headerLength);
  responseClient.write(frame->buf, frame->len);
  esp_camera_fb_return(frame);
}

void initializeWirelessServer() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  if (!WiFi.config(ESP_ADDRESS, PI_GATEWAY, SUBNET_MASK, PI_GATEWAY)) {
    Serial.println("ERROR: Failed to configure the ESP Wi-Fi address.");
    return;
  }

  Serial.printf("Connecting to Pi Wi-Fi network: %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  const unsigned long connectionStart = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - connectionStart < 20000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(
        "ERROR: Could not connect to the Pi hotspot; will keep retrying.");
  } else {
    Serial.printf(
        "Connected to Pi hotspot. ESP IP: %s, signal: %d dBm\n",
        WiFi.localIP().toString().c_str(), WiFi.RSSI());
  }

  server.on("/shift", HTTP_GET, sendShiftResponse);
  server.on("/calibrate", HTTP_POST, calibrateFromCurrentDetection);
  server.on("/reset-reference", HTTP_POST, restoreStandardReference);
  server.on("/debug-frame", HTTP_GET, sendDebugFrame);
  server.on("/health", HTTP_GET, []() {
    server.send(200, "application/json", "{\"ok\":true}");
  });
  server.begin();

  Serial.printf("ESP Wi-Fi address: http://%s/shift\n",
                ESP_ADDRESS.toString().c_str());
}

void handleSerialCommand() {
  while (Serial.available()) {
    const char command = Serial.read();

    if (command == 'c' || command == 'C') {
      if (isnan(latestCenter)) {
        Serial.println("Cannot calibrate: no chip is currently detected.");
      } else {
        referenceCenter = latestCenter;
        preferences.putFloat("refCenter", referenceCenter);
        Serial.printf("Saved reference center: %.1f px\n", referenceCenter);
      }
    } else if (command == 'r' || command == 'R') {
      preferences.remove("refCenter");
      referenceCenter = STANDARD_CHIP_CENTER;
      Serial.printf(
          "Live calibration erased; restored standard-chip reference: %.1f px\n",
          referenceCenter);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\nESP32-S3 chip-shift detector");

  preferences.begin("chip-shift", false);
  referenceCenter =
      preferences.getFloat("refCenter", STANDARD_CHIP_CENTER);

  if (!initializeCamera()) {
    Serial.println("Stopped.");
    while (true) {
      delay(1000);
    }
  }

  initializeWirelessServer();

  if (preferences.isKey("refCenter")) {
    Serial.printf("Loaded live reference center: %.1f px\n", referenceCenter);
  } else {
    Serial.printf(
        "Using Images/standard_chip.png reference center: %.1f px\n",
        referenceCenter);
  }
}

void loop() {
  static unsigned long previousReconnectAttempt = 0;
  if (WiFi.status() != WL_CONNECTED &&
      millis() - previousReconnectAttempt >= WIFI_RECONNECT_INTERVAL_MS) {
    previousReconnectAttempt = millis();
    Serial.printf("Wi-Fi disconnected (status %d); retrying...\n",
                  WiFi.status());
    WiFi.reconnect();
  }

  server.handleClient();
  handleSerialCommand();

  delay(10);
}

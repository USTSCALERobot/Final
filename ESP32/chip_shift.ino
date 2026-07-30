/*
    Ryan Bercich
    University of St. Thomas
    30 July 2026
    chip_shift.ino

    ***NOTE this file is intended to be compiled with the Arduino IDE for an ESP32-CAM board. It is here for reference only.***

  ESP32-CAM port of chip_shift.py

  Default hardware: AI-Thinker ESP32-CAM with OV2640 camera.

  Serial commands:
    c  Save the current chip center as the reference position
    r  Erase a live calibration and restore the standard-chip reference

  Image coordinates increase downward. A positive shift therefore means that
  the detected chip is lower in the image than the saved reference.
*/

#include "esp_camera.h"
#include <Preferences.h>

// AI-Thinker ESP32-CAM camera pins.
#define PWDN_GPIO_NUM  32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM   0
#define SIOD_GPIO_NUM  26
#define SIOC_GPIO_NUM  27
#define Y9_GPIO_NUM    35
#define Y8_GPIO_NUM    34
#define Y7_GPIO_NUM    39
#define Y6_GPIO_NUM    36
#define Y5_GPIO_NUM    21
#define Y4_GPIO_NUM    19
#define Y3_GPIO_NUM    18
#define Y2_GPIO_NUM     5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM  23
#define PCLK_GPIO_NUM  22

// Same ROI used by chip_shift.py for a 320 x 240 image.
constexpr int ROI_X = 130;
constexpr int ROI_Y = 0;
constexpr int ROI_W = 40;
constexpr int ROI_H = 190;

constexpr float MIN_ROW_OCCUPANCY = 0.60f;
constexpr int MIN_RUN_LENGTH = 18;
constexpr unsigned long SAMPLE_INTERVAL_MS = 500;

// Reference produced by running this sketch's detection algorithm against
// Images/standard_chip.png (320 x 240): longest occupied run = rows 133..189,
// so its center is (133 + 189) / 2 = 161.0 px.
constexpr float STANDARD_CHIP_CENTER = 161.0f;

Preferences preferences;
float referenceCenter = STANDARD_CHIP_CENTER;
float latestCenter = NAN;

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

    if (start < ROI_H && end - start + 1 >= MIN_RUN_LENGTH &&
        (bestStart < 0 || end - start > bestEnd - bestStart)) {
      bestStart = start;
      bestEnd = end;
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
  return true;
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
  Serial.println("\nESP32-CAM chip-shift detector");

  preferences.begin("chip-shift", false);
  referenceCenter =
      preferences.getFloat("refCenter", STANDARD_CHIP_CENTER);

  if (!initializeCamera()) {
    Serial.println("Stopped.");
    while (true) {
      delay(1000);
    }
  }

  if (preferences.isKey("refCenter")) {
    Serial.printf("Loaded live reference center: %.1f px\n", referenceCenter);
  } else {
    Serial.printf(
        "Using Images/standard_chip.png reference center: %.1f px\n",
        referenceCenter);
  }
}

void loop() {
  handleSerialCommand();

  static unsigned long previousSample = 0;
  if (millis() - previousSample < SAMPLE_INTERVAL_MS) {
    delay(10);
    return;
  }
  previousSample = millis();

  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    Serial.println("ERROR: Camera capture failed.");
    return;
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
    Serial.println("No chip found; adjust ROI or lighting.");
    return;
  }

  Serial.printf(
      "center=%.1f px, confidence=%.0f%%, threshold=%u",
      latestCenter, confidence * 100.0f, threshold);

  if (!isnan(referenceCenter)) {
    const float shift = latestCenter - referenceCenter;
    const char *direction =
        shift > 0.05f ? "down" : shift < -0.05f ? "up" : "centered";
    Serial.printf(", shift=%.1f px %s", fabsf(shift), direction);
  }
  Serial.println();
}

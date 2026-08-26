//Louis Stevenson
//ESP firmware transmitter code

#include <WiFi.h>
#include "esp_camera.h"

// =======================
// WiFi Settings
// =======================

const char* ssid = "";
const char* password = "";

IPAddress piAddress();   // Raspberry Pi hotspot IP
const uint16_t piPort = 5000;

WiFiClient client;


// =======================
// ESP32-S3 Sense Camera Pins
// Adjust if your board differs
// =======================

#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1

#define XCLK_GPIO_NUM     10
#define SIOD_GPIO_NUM     40
#define SIOC_GPIO_NUM     39

#define Y9_GPIO_NUM       48
#define Y8_GPIO_NUM       11
#define Y7_GPIO_NUM       12
#define Y6_GPIO_NUM       14
#define Y5_GPIO_NUM       16
#define Y4_GPIO_NUM       18
#define Y3_GPIO_NUM       17
#define Y2_GPIO_NUM       15

#define VSYNC_GPIO_NUM    38
#define HREF_GPIO_NUM     47
#define PCLK_GPIO_NUM     13



void setupCamera()
{
    camera_config_t config;

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

    config.pin_sscb_sda = SIOD_GPIO_NUM;
    config.pin_sscb_scl = SIOC_GPIO_NUM;

    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;


    config.xclk_freq_hz = 20000000;

    // JPEG output
    config.pixel_format = PIXFORMAT_JPEG;

    // Resolution
    config.frame_size = FRAMESIZE_QVGA; // 320x240

    // JPEG quality
    // 10-15 is usually good
    config.jpeg_quality = 4;

    // Use PSRAM buffers
    config.fb_count = 2;


    esp_err_t result = esp_camera_init(&config);

    if(result != ESP_OK)
    {
        Serial.printf(
            "Camera init failed: 0x%x\n",
            result
        );

        while(true);
    }
    
  sensor_t *s = esp_camera_sensor_get();

  s->set_vflip(s, 1);     // Flip image vertically
  s->set_hmirror(s, 0);   // No horizontal mirror

  Serial.println("Camera initialized");
}



void connectWiFi()
{
    WiFi.begin(ssid,password);

    Serial.print("Connecting");

    while(WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println("\nConnected");
}



bool connectPi()
{
    if(client.connected())
        return true;


    Serial.println("Connecting to Pi...");

    if(client.connect(piAddress,piPort))
    {
        Serial.println("Connected to Pi");
        return true;
    }

    Serial.println("Pi connection failed");
    return false;
}



void sendFrame()
{
    camera_fb_t *fb = esp_camera_fb_get();

    if(!fb)
    {
        Serial.println("Camera capture failed");
        return;
    }


    if(!connectPi())
    {
        esp_camera_fb_return(fb);
        return;
    }


    uint32_t imageSize = fb->len;


    // Send 4-byte size header
    uint32_t sizeNetworkOrder = htonl(imageSize);

    client.write(
        (uint8_t*)&sizeNetworkOrder,
        sizeof(sizeNetworkOrder)
    );


    // Send JPEG bytes
    size_t sent = 0;

    while(sent < imageSize)
    {
        size_t chunk =
            client.write(
                fb->buf + sent,
                imageSize - sent
            );

        if(chunk == 0)
        {
            Serial.println("Send failed");
            break;
        }

        sent += chunk;
    }


    Serial.printf(
        "Sent JPEG: %d bytes\n",
        imageSize
    );


    esp_camera_fb_return(fb);
}



void setup()
{
    Serial.begin(115200);

    setupCamera();

    connectWiFi();
}



void loop()
{
    sendFrame();

    delay(100);   // ~10 FPS target
}

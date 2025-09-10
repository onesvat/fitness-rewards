#include <WiFi.h>
#include <HTTPClient.h>

// -- Configuration --
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* webhookUrl = "http://your-server.com/webhook";
const char* deviceId = "fitness-tracker-01";
const char* apiKey = "your-secret-api-key-123";  // Must match the server's API key

// Timeout thresholds (in milliseconds)
#define PAUSE_TIMEOUT 5000      // 5 seconds of inactivity to trigger pause
#define STOP_TIMEOUT 30000      // 30 seconds of inactivity to trigger stop
#define REVOLUTION_SEND_INTERVAL 10000 // Send revolution count every 10 seconds
#define WIFI_RECONNECT_INTERVAL 20000 // Attempt to reconnect WiFi every 20 seconds

// Specify which GPIO pin you connected to
#define SENSOR_PIN 23

// -- State Management --
enum WorkoutState {
  STOPPED,
  RUNNING,
  PAUSED
};
WorkoutState currentWorkoutState = STOPPED;
String workoutId = "";

// volatile: Indicates that this variable can be changed within an interrupt.
volatile unsigned long revolutionCounter = 0;
volatile unsigned long lastInterruptTime = 0;

// Timers
unsigned long lastRevolutionSendTime = 0;
unsigned long lastWiFiCheckTime = 0;

// -- Function Prototypes --
void ICACHE_RAM_ATTR revolutionDetected();
void setupWiFi();
void ensureWiFiConnected();
bool sendWebhook(String event, int count = 0);
void handleWorkoutState();
void handleRevolutionSending();

// -- Interrupt Service Routine --
// This function runs in RAM for faster execution when a revolution is detected.
void ICACHE_RAM_ATTR revolutionDetected() {
  static unsigned long lastDebounceTime = 0;
  unsigned long interruptTime = millis();
  // Debounce to prevent multiple triggers from a single magnet pass
  if (interruptTime - lastDebounceTime > 20) {
    revolutionCounter++;
    lastInterruptTime = interruptTime;
    lastDebounceTime = interruptTime;
  }
}

// -- WiFi and Webhook Functions --
void setupWiFi() {
  Serial.print("Connecting to ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) { // Try for 10 seconds
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected.");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nFailed to connect to WiFi. Will retry in the background.");
  }
}

void ensureWiFiConnected() {
    unsigned long currentTime = millis();
    if (WiFi.status() != WL_CONNECTED && (currentTime - lastWiFiCheckTime > WIFI_RECONNECT_INTERVAL)) {
        Serial.println("WiFi disconnected. Attempting to reconnect...");
        WiFi.reconnect();
        lastWiFiCheckTime = currentTime;
    }
}

bool sendWebhook(String event, int count = 0) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected. Cannot send webhook.");
    return false;
  }

  HTTPClient http;
  String url = String(webhookUrl) + "?deviceId=" + String(deviceId) + "&workoutId=" + workoutId + "&event=" + event;
  if (event == "revolution_add" && count > 0) {
    url += "&count=" + String(count);
  }

  http.begin(url);
  
  // Add API key authentication header
  http.addHeader("x-api-key", apiKey);
  
  Serial.print("Sending webhook: ");
  Serial.println(url);

  int httpResponseCode = http.GET();

  if (httpResponseCode > 0) {
    Serial.printf("HTTP Response code: %d\n", httpResponseCode);
    http.end();
    return httpResponseCode == 200;
  } else {
    Serial.printf("Error on sending GET: %s\n", http.errorToString(httpResponseCode).c_str());
    http.end();
    return false;
  }
}

// -- Main Application Logic --
void setup() {
  Serial.begin(115200);
  Serial.println("\nFitness Tracker Initializing...");

  setupWiFi();

  pinMode(SENSOR_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(SENSOR_PIN), revolutionDetected, FALLING);
  
  Serial.println("Setup complete. Waiting for workout to start...");
}

void handleWorkoutState() {
  unsigned long currentTime = millis();
  // Check if a revolution has happened since the last state check
  bool activityDetected = lastInterruptTime > 0 && lastInterruptTime > (currentTime - PAUSE_TIMEOUT);

  switch (currentWorkoutState) {
    case STOPPED:
      if (activityDetected) {
        currentWorkoutState = RUNNING;
        workoutId = String(currentTime); // New workout ID
        Serial.println("Workout Started!");
        sendWebhook("started");
      }
      break;

    case PAUSED:
      if (activityDetected) {
        currentWorkoutState = RUNNING;
        Serial.println("Workout Resumed!");
        sendWebhook("resumed");
      } else if (currentTime - lastInterruptTime > STOP_TIMEOUT) {
        currentWorkoutState = STOPPED;
        Serial.println("Workout Stopped.");
        sendWebhook("stopped");
        // Reset for next workout
        workoutId = "";
        revolutionCounter = 0;
        lastInterruptTime = 0;
      }
      break;

    case RUNNING:
      if (currentTime - lastInterruptTime > PAUSE_TIMEOUT && lastInterruptTime > 0) {
        currentWorkoutState = PAUSED;
        Serial.println("Workout Paused.");
        sendWebhook("paused");
      }
      break;
  }
}

void handleRevolutionSending() {
  unsigned long currentTime = millis();
  if (currentWorkoutState != STOPPED && (currentTime - lastRevolutionSendTime > REVOLUTION_SEND_INTERVAL)) {
    noInterrupts();
    unsigned long countToSend = revolutionCounter;
    interrupts();

    if (countToSend > 0) {
      if (sendWebhook("revolution_add", countToSend)) {
        // Webhook successful, subtract the sent count from the total
        noInterrupts();
        revolutionCounter -= countToSend;
        interrupts();
        Serial.printf("%lu revolutions sent and counter updated.\n", countToSend);
      } else {
        Serial.println("Failed to send revolution count. Will retry next interval.");
      }
    }
    lastRevolutionSendTime = currentTime;
  }
}

void loop() {
  ensureWiFiConnected();
  handleWorkoutState();
  handleRevolutionSending();
  
  // A small delay to keep the loop from running too fast and allow the ESP32 to handle background tasks.
  delay(100);
}

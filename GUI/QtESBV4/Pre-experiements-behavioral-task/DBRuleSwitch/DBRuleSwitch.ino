#include <Keyboard.h>
#include <string.h>
#include <SD.h>
#include <SPI.h> // SD card

#include "gpSMART_Habits.h" // For State Machine

/* Connection: Teensy <<===Serial===>> PC */

/****************************************************************************************************/
/********************************************** Public *********************************************/
/****************************************************************************************************/

/********** SD card **********/
const byte chipSelect = BUILTIN_SDCARD; // Teensy 3.5 & 3.6 & 4.1 on-board SD card
String string_tmp;

/********** Port Definition **********/
const byte switchPin = 4; // ToggerSwitch pin to start/pause experiment
const byte ledPin = 13;   // LED pin

// Events: record all the events happened during one loop
typedef struct
{
  int events_num = 0;
  unsigned long events_time[20] = {};
  byte events_id[20] = {}; /* 1: restart; 2: free reward; */
  int events_value[20] = {0};
} Events;
Events Ev;

/********** Other public **********/
static void FLASHLED(uint16_t duration_ms)
{
  digitalWrite(ledPin, HIGH);
  delay(duration_ms);
  digitalWrite(ledPin, LOW);
}

/********** gpSMART **********/
bool CaptempFlag = 1;
gpSMART smart;
extern TrialResult trial_res;
extern volatile bool smartFinished; // Has the system exited the matrix (final state)?
extern volatile bool smartRunning;  // 1 if state matrix is running
extern byte smartFlag[5];

// noise
const byte noisePin = 3;
byte LowBit;

/********** Trial related **********/
#define RECORD_TRIALS 100      // record recent 100 trials history
const byte recent_trials = 50; // Calculate performance for rencent 50 trials
// Define  RewardFlag struct.
typedef struct
{
  byte flag_L_water;
  byte flag_R_water;
  byte flag_M_water;
  unsigned int past_trials;
} RewardFlag;

typedef struct
{ 
  // Public
  unsigned int currTrialNum = 0;       // current trial number
  byte currProtocolIndex = 0;          // index of Protocol
  unsigned int currProtocolTrials = 0; // number of trials in current protocol
  float currProtocolPerf = 0;           // performance: 0-100%
  byte TrialPresentMode = 0;           // 0"pattern",1"random",2"antiBias",3"fixed"
  byte ProtocolIndexHistory[RECORD_TRIALS] = {};
  byte TrialTypeHistory[RECORD_TRIALS] = {}; // 0 undef; 1 left; 2 right; 3 middle;
  byte Stimu1History[RECORD_TRIALS] = {}; // 0 undef; 1 left; 2 right; 3 middle;
  byte Stimu2History[RECORD_TRIALS] = {}; // 0 undef; 1 left; 2 right; 3 middle;
  byte OutcomeHistory[RECORD_TRIALS] = {};   // 0 no-response; 1 correct; 2 error; 3 others
  byte SampleTypeHistory[RECORD_TRIALS] = {};   // 0~3 contrast diff; 3 others
  byte EarlyLickHistory[RECORD_TRIALS] = {}; // 0-no earlylick; 1-earlylick; 2-undef
  unsigned int totalRewardNum = 0;
  unsigned int retention_counter = 0;
  byte reward_left = 30;
  byte reward_right = 30;
  byte reward_middle = 30;
  byte high_light_intensity = 255;
  byte low_light_intensity = 1;
  unsigned long Trial_txt_position = 0;     // currently Trial file cursor position
  unsigned long Tevent_txt_position = 0;    // currently Tevent file cursor position
  RewardFlag GaveFreeReward = {0, 0, 0, 0}; // [freeReward flag L, R, M, past_trials] todo...

  // Task-specific
  int TrialBlockInitPeriod = 100;
  int SamplePeriod = 500;
  int DelayPeriod = 200;
  int PreCueDelayPeriod = 100;
  int PreCuePeriod = 1000;
  int TimeOut = 2000;
  int AnswerPeriod = 10000;
  int ConsumptionPeriod = 750;
  int StopLickingPeriod = 1000;
  int EarlyLickPeriod = 100;
  int extra_TimeOut = 0;
  unsigned int hardestTrials = 0;
  int rule = 1;
} Parameters_behavior;
Parameters_behavior S;

/********** Define OutputAction**********/
OutputAction LeftWaterOutput = {"DO1", 1};
OutputAction RightWaterOutput = {"DO2", 1};

OutputAction NoSoundOutput = {"DO3", 0};
/// @brief /////////////// top buzz sound
OutputAction CueOutput = {"tPWM2", 6}; // 3KHz
OutputAction NoiseOutput = {"Flag1", 1};

/// @brief /////////////// left buzz sound
OutputAction LeftLowSoundOutput = {"tPWM1", 1};  // tPWM1 left sound , 8KHz
OutputAction LeftHighSoundOutput = {"tPWM1", 2};  // tPWM1 left sound, 32KHz
OutputAction LeftCueSoundOutput = {"tPWM1", 3};  // tPWM1 left sound , 16KHz

OutputAction LeftLowMidSoundOutput = {"tPWM1", 4};  // tPWM1 left sound, 11K
OutputAction LeftHighMidSoundOutput = {"tPWM1", 5};  // tPWM1 left sound , 22KHz

/// @brief /////////////// right buzz sound
OutputAction RightLowSoundOutput = {"tPWM3", 1}; // tPWM3 right sound 
OutputAction RightHighSoundOutput = {"tPWM3", 2}; // tPWM3 right sound 
OutputAction RightCueSoundOutput = {"tPWM3", 3}; // tPWM3 right sound 

OutputAction RightLowMidSoundOutput = {"tPWM3", 4}; // tPWM3 right sound 
OutputAction RightHighMidSoundOutput = {"tPWM3", 5}; // tPWM3 right sound 

// Note: the freq setting is working for all regular PWM below
OutputAction LeftLightOutput = {"PWM1", S.low_light_intensity};  // left light, value 0-255
OutputAction RightLightOutput = {"PWM5", S.low_light_intensity}; // right light ,same as above
OutputAction LeftLightOutputH = {"PWM1", S.high_light_intensity};  // High left light intensity
OutputAction RightLightOutputH = {"PWM5", S.high_light_intensity}; // High right light intensity

OutputAction BlueLightOutput = {"PWM4", S.high_light_intensity};  // Blue light...
OutputAction RedLightOutput = {"PWM2", S.high_light_intensity};   // red light...
OutputAction GreenLightOutput = {"PWM3", S.high_light_intensity}; // Green light...
OutputAction BlueLightOutputBackground = {"PWM4", S.low_light_intensity};  // Blue light Background...
OutputAction RedLightOutputBackground = {"PWM2", S.low_light_intensity};   // red light Background...
OutputAction GreenLightOutputBackground = {"PWM3", S.low_light_intensity}; // Green light Background...

OutputAction TimeAlignmentOutput = {"DACTimeAlignment", 1}; // send a time alignment signal to PC
OutputAction SpikeRecordingOutput = {"SerialCode", 2}; // open mode Spike
OutputAction LFPRecordingOutput = {"SerialCode",1}; // open mode LFP
OutputAction Inactive_Output = {"Flag2", 1};
OutputAction smartFinish_Output = {"Flag4", 1};
OutputAction Inavailable_Output = {"Flag5", 1};

OutputAction CapReinitOutput = {"Flag3" , 1}; // Flag 2: cap disable; 1: re init
OutputAction CapDisableOutput = {"Flag3" , 2}; // Flag 2: cap disable; 1: re init
// sound frequency ;sound orients ;light orients ;reversal trials ;wavelength ;light intensity;

byte TrialOutcome = 3;      // 0 no-response; 1 correct; 2 error; 3 others
byte is_earlylick = 2;      // 0-no earlylick; 1-earlylick; 2-undef
byte MaxSame = 3;
byte MinCorrect = 1; // minimum correct trials in the last 5 trials
byte Perf100 = 0;
byte EarlyLick100 = 0;
unsigned long last_reward_time = 0;
unsigned long last_update_time = 0;
int timed_reward_count = 0;

int EL_Favor = 2; // 2 no favor; 0 favor
int CatchTrialProb = 5; // use a small number of trials as catch trials: baseline trial no sample cue
int BaselineTrialFlag = 0; // 0 no catch trial; 1 catch trials

byte pause_signal_PC = 0;
byte tare_flag = 1;
byte tare_length = 0;
bool paused = 1;
byte ledState = LOW;
byte TrialBlockOnset = 1; // current trial is the first trial of trialblock

float Alpha50 = 0.98;
float Alpha100 = 0.99;
float Alpha500 = 0.998;
float currProtocolPerf_corrected = 0;

byte TrialType  = 1;         // 0 undef; 1 left; 2 right; 3 middle;
byte SampleType = 1;        // contrast
float currStimu[2] = {1 ,1}; // contrast; stimu1: sound orientation[-1, 1]; stimu2: sound freq[-1, -0.5, 0, 0.5, 1]

float S1Feat[2] = {-1.0, 1.0};
float S2Feat[5] = {-1.0, -0.5, 0.0, 0.5, 1.0};
/********** Communication ***********/
char packetBuffer[255];      // buffer to hold incoming packet
char outBuffer[1000];        // buffer to hold outcoming packet,UDP max 1472
int cage_id = 101;
char task_name[40];

 /********** Time alignment DAC parameter ***********/
const float    FREQ        = 5000.0f;                  // 2 kHz
const float    FS          = AUDIO_SAMPLE_RATE_EXACT;  // ≈ 44.1 kHz
const int      SEG_SAMPLES = 44;                       // 1 ms ≈ 44 样本（0.998 ms）
const int16_t  AMP         = 32766;                    // 全幅
const int16_t  zero_voltage         = -32768;  
/****************************************************************************************************/
/********************************************** Setup() *********************************************/
/****************************************************************************************************/

void setup()
{
  delay(3000);          // for debug
  Serial.begin(115200); // initialize seiral for debugging
  pinMode(ledPin, OUTPUT);
  pinMode(switchPin, INPUT_PULLUP); // low if switch on; hight if switch off

  /********** DAC sine output for time alignment***********/
  AudioMemory(20);
  queue1.setBehaviour(AudioPlayQueue::NON_STALLING);
  queue1.setMaxBuffers(20);
  dc1.amplitude(-1.0);
  int16_t seg_sine[SEG_SAMPLES];
  float dphi = 2.0f * M_PI * FREQ / FS;
  float phi  = 0.0f;
  for (int i = 0; i < SEG_SAMPLES; ++i) {
    seg_sine[i] = (int16_t)(AMP * sinf(phi));
    phi += dphi;
  }
 
  // 2) block0 布局：正弦(0..43) → 0V(44..87) → 正弦(88..127 前40)
  memset(block0, 0, sizeof(block0));
  for (int i = 0; i < SEG_SAMPLES; ++i) {         // 段1：正弦
    block0[i] = seg_sine[i];
  }
  for (int i = 0; i < SEG_SAMPLES; ++i) {          // 段2：0V
    block0[SEG_SAMPLES + i] = zero_voltage;
  }
  for (int j = 0; j < 40; ++j) {                   // 段3前 40 样本：正弦
    block0[2*SEG_SAMPLES + j] = seg_sine[j];
  }
  // 3) block1 布局：正弦剩余 4 样本 → 其余填 0（播放后保持 0V）
  memset(block1, 0, sizeof(block1));
  for (int j = 40; j < SEG_SAMPLES; ++j) {        // 段3剩余 4 样本
    block1[j - 40] = seg_sine[j];
  }
  for (int j = 4; j < 128; ++j) {        // 段3剩余 0V
    block1[j] = zero_voltage;
  }
  // 3) block2 布局其余填 0（播放后保持 0V）
  for (int j = 0; j < 128; ++j) {        // 段3剩余 0V
    block2[j] = zero_voltage;
  }
  /********** SD card ***********/
  if (!SD.begin(chipSelect))
  {
    Serial.println("SD Card failed, or not present");
    return; // don't do anything more:
  }
  else
  {
    Serial.println("SD is working...");
  }
  if (read_SD_cage_info() < 0)
  { // read cage_id
    cage_id = 101;
    sprintf(task_name, "TBD");
  }
  FLASHLED(200);

  /********** gpSMART ***********/
  smart.init(2); // init smart with num_electrodes used
  smart.setLicksDetectionEnabled(0);
  byte PortEnabled[4] = {1, 0, 0, 0};
  smart.setDigitalInputsEnabled(PortEnabled);
  /// tPWM2: top
  smart.setTruePWMFrequency(2, 1, 8000, 128);  // (low sound) byte tPWM_num, byte freq_num, uint32 frequency, byte duty
  smart.setTruePWMFrequency(2, 2, 32000, 128); // (high sound) byte tPWM_num, byte freq_num, uint32 frequency, byte duty
  smart.setTruePWMFrequency(2, 3, 16000, 128); // (go cue) byte tPWM_num, byte freq_num, uint32 frequency, byte duty

  smart.setTruePWMFrequency(2, 4, 11314, 128);
  smart.setTruePWMFrequency(2, 5, 22627, 128);
  smart.setTruePWMFrequency(2, 6, 3000, 128);  // (low sound) byte tPWM_num, byte freq_num, uint32 frequency, byte duty

  // tPWM1: left sound;
  smart.setTruePWMFrequency(1, 1, 8000, 128);  // (low sound) byte tPWM_num, byte freq_num, uint32 frequency, byte duty
  smart.setTruePWMFrequency(1, 2, 32000, 128); // (high sound) byte tPWM_num, byte freq_num, uint32 frequency, byte duty
  smart.setTruePWMFrequency(1, 3, 16000, 128); // (go cue) byte tPWM_num, byte freq_num, uint32 frequency, byte duty

  smart.setTruePWMFrequency(1, 4, 11314, 128);
  smart.setTruePWMFrequency(1, 5, 22627, 128);

  
  //  tPWM3: right sound
  smart.setTruePWMFrequency(3, 1, 8000, 128);  // (low sound) byte tPWM_num, byte freq_num, uint32 frequency, byte duty
  smart.setTruePWMFrequency(3, 2, 32000, 128); // (high sound) byte tPWM_num, byte freq_num, uint32 frequency, byte duty
  smart.setTruePWMFrequency(3, 3, 16000, 128); // (go cue) byte tPWM_num, byte freq_num, uint32 frequency, byte duty

  smart.setTruePWMFrequency(3, 4, 11314, 128);
  smart.setTruePWMFrequency(3, 5, 22627, 128);
  FLASHLED(200);

  // read parameters from SD Card to override S
  read_SD_para_S();
  // write an artificial event to mark the restart of Arduino board
  Ev.events_num = 0;
  Ev.events_id[Ev.events_num] = 1; // restart;
  Ev.events_time[Ev.events_num] = Teensy3Clock.get();
  Ev.events_value[Ev.events_num] = -1;
  Ev.events_num = 1;
  write_SD_event(); // write event to file
  Ev.events_num = 0;
  // random seeds
  randomSeed(analogRead(0));

  /********** Online Communication ***********/
  sprintf(outBuffer, "SE: Cage %d is online now; IP: %s", cage_id, task_name); // Special message starts with 'S'
  Serial.println(outBuffer);
  FLASHLED(200);

  digitalWrite(ledPin, HIGH); // Light up LED to indicate init finished
}

/****************************************************************************************************/
/********************************************** Loop() **********************************************/
/****************************************************************************************************/
void loop()
{
  // Check if the toggle switch is ON
  if (digitalRead(switchPin) == 0 && pause_signal_PC == 0)
  { // if yes, run the state matrix
    if (paused == 1)
    {
      paused = 0;
      digitalWrite(ledPin, HIGH);
      Serial.println("M: Program RESUME!!!");
      // in case SD card was removed and re-insert, need re-initilization
      SD.begin(chipSelect);
      read_SD_para_S();
      // free reward to fill the lickport tube
      free_reward(30);
    }

    if (smartFlag[3]) // smartFinish
    { // i.e., a trial is done
      smartFlag[3] = false;
      digitalWrite(ledPin, HIGH);
      S.currTrialNum++;

      UpdateTrialOutcome();  // including white noise (if error) and inter-trial interval
      write_SD_trial_info(); // log trial info and event to SD
      SendTrialInfo2PC();    // send trial info to PC through Serial

      //////////// for next trial ///////////
      autoChangeProtocol(); // Change protocol and parameters based on performance;
      autoReward();         // Set Reward Flag if many wrongs in a row;
      trialSelection();     // determine TrialType;
      write_SD_para_S();    // write parameter S (updated after this trial) to SD card;
      //////////// for next trial ///////////
    }
    else if (!smartRunning)
    {
      construct_matrix_and_Run();
      digitalWrite(ledPin, LOW); // Teensy led does not support PWM
    }

    // White noise for error trial or background stimuli
    if (smartFlag[0] == 1)
    {
      digitalWrite(noisePin, LowBit); // about 55 us/bit
      LowBit = random(2);
    }
    else
    {
      digitalWrite(noisePin, LOW);
    }
    // cap reinit
    if (smartFlag[2] == 1)
    {
      smart.reinitCap(2); // 注意： 在运行这个重启 cap的时候必须保证cap 传感器没有被调用；否则会在初始化过程中调用cap导致错误；所以必须要setLicksDetectionEnabled 为0的时候去更新
      smart.setLicksDetectionEnabled(1);
      smartFlag[2] = 0;
    }
     // cap disable
    if (smartFlag[2] == 2)
    {
      smart.setLicksDetectionEnabled(0);
      smartFlag[2] = 0;
    }

    // trial block setup
    if(smartFlag[1]){
      // Trial block end: inactive
      TrialBlockOnset = 1;
      analogWrite(9, S.high_light_intensity);
      }else{// actived
        analogWrite(9, 0);
      }
    
    // Trial init led feedback
    if (millis() - last_update_time > 10){
      last_update_time = millis();
      if(digitalRead(gpSMART_DI_Lines[0]) == 0 && smartFlag[4] == 0){ // holding the port
        analogWrite(5, S.low_light_intensity);
        analogWrite(20, S.low_light_intensity);
      }
      else{
        analogWrite(5, 0);
        analogWrite(20, 0);
      }
    } 

    if (millis() - last_reward_time > 3 * 3600000)
    { // there is no reward in last 3 hours
      // free reward to fill the lickport tube
      free_reward(50);
      last_reward_time = millis();
      Serial.println("M: No Reward in Last 3 Hours.");

      timed_reward_count++;

      if (timed_reward_count >= 4)
      { // in last 12 hours no reward
        timed_reward_count = 0;
        // more free reward to fill the lickport tube
        free_reward(100);
        last_reward_time = millis();
        Serial.println("E: No Reward in Last 12 Hours.");
      }
    }

    // write current event info
    if (Ev.events_num > 0)
    {
      write_SD_event();
      Ev.events_num = 0;
    }
  }

  else
  { // if the toggle switch is off
    if (paused == 0)
    {
      paused = 1; // execute only one time
      smart.Stop();
      Serial.println("M: Program PAUSED!!!");
      smart.setLicksDetectionEnabled(0);
    }
    // Flashing LED
    if (ledState == LOW)
    {
      ledState = HIGH;
    }
    else
    {
      ledState = LOW;
    }
    digitalWrite(ledPin, ledState);
    delay(200);
    // stimulus valve check
    // auditory top(high) -> top(low) -> left -> right 
//    system_output_check();
  }

  /********** Serial communication with PC ***********/
  if (Serial.available() > 0)
  {                              // receiving data from PC
    Serial.readBytes(packetBuffer, 255); // int len = ...
    byte commandByte = packetBuffer[0];
    // T for Time calibration,
    switch (commandByte)
    {
    case 'T':                                   // system test
    if (smartFlag[1] == 1) // Inactive output
      {
        Teensy3Clock.set(atoi(&packetBuffer[1])); // str2int
      // if the state machine is not running , then align the time between HABITS and wireless recorder
        system_output_check();
      }
      break;
    case 'P': // Pause the system
      pause_signal_PC = 1;
      break;
    case 'M': // resuMe the system
      pause_signal_PC = 0;
      break;
    case 'R': // set reward values for left, right and middle
    {
      String packetString = packetBuffer;
      int ind1 = packetString.indexOf(',');                            // finds location of first ,
      S.reward_left = packetString.substring(1, ind1).toInt();         // captures first data String
      int ind2 = packetString.indexOf(',', ind1 + 1);                  // finds location of second ,
      S.reward_right = packetString.substring(ind1 + 1, ind2).toInt(); // captures second data String
      int ind3 = packetString.indexOf(',', ind2 + 1);
      S.reward_middle = packetString.substring(ind2 + 1, ind3).toInt();
      write_SD_para_S();
      free_reward(S.reward_left);
      break;
    }
    case 'L': // set Light intensity value for low and high
    {
      String packetString = packetBuffer;
      int ind1 = packetString.indexOf(',');                                    // finds location of first ,
      S.low_light_intensity = packetString.substring(1, ind1).toInt();         // captures first data String
      int ind2 = packetString.indexOf(',', ind1 + 1);                          // finds location of second ,
      S.high_light_intensity = packetString.substring(ind1 + 1, ind2).toInt(); // captures second data String TODO bug
      write_SD_para_S();
      free_reward(S.reward_left);
      break;
    }
    case 'A': // read All info
      // send back all info in control panel, like reward values,
      sprintf(outBuffer, "A%d;%d;%d;%d;%d;%d;%d;%lu;%d;", S.reward_left, S.reward_right, S.reward_middle, S.low_light_intensity, S.high_light_intensity, S.currProtocolIndex, 0, Teensy3Clock.get(), S.extra_TimeOut);
      Serial.println(outBuffer);
      break;
    case 'H': // 'S'pecical msg: 'H'andshake
      Serial.println("SH");
      smart.ManualTimeAlignment(); // 电磁脉冲标记
      break;
    case 'Z': // Protocol manual change
    {
      String packetString = packetBuffer;
      int ind1 = packetString.indexOf(',');                          // finds location of first ,
      S.currProtocolIndex = packetString.substring(1, ind1).toInt(); // captures first data String
      write_SD_para_S();
      free_reward(S.reward_left);
      break;
    }
    case 'E': // Extra timeout reciever
    {
      String packetString = packetBuffer;
      int ind1 = packetString.indexOf(',');                      // finds location of first ,
      S.extra_TimeOut = packetString.substring(1, ind1).toInt(); // captures first data String
      write_SD_para_S();
      free_reward(S.reward_left);
      break;
    }
    default: // never happen...
      Serial.println("E: Serial received some unusual packets!");
      break;
    }
  }

} // end of loop()

/****************************************************************************************************/
/********************************************** Functions *******************************************/
/****************************************************************************************************/

int exponent(float beta, float min, float max)
{
  float u;
  float x;
  int period;
  for (;;)
  {
    u = float(float(random(0, 1000)) / float(1000));
    x = -beta * log(u);
    if (min < x && x < max)
    {
      period = int(x * 1000);
      return period;
    }
  }
}

void construct_matrix_and_Run()
{
  /* Final trial structure
   *  Self-trigger(500 ms) -> TrialStart -> SamplePeriod(500 ms) -> DelayPeriod(800~1200 ms) -> Cue(100 ms) -> ResponsePeriod -> TrialEnd
   *  [---------------------------------EarlyLick inhibitation-----------------------------------]
   */
  OutputAction LeftLightOutput = {"PWM1", S.low_light_intensity};  // left light, value 0-255,TODO just 1 ,the light intensity is unaffordable(anlogWrite()command)
  OutputAction RightLightOutput = {"PWM5", S.low_light_intensity}; // right light ,same as above

  OutputAction BlueLightOutput = {"PWM4", S.high_light_intensity};           // Blue light...
  OutputAction RedLightOutput = {"PWM2", S.high_light_intensity};            // red light...
  OutputAction GreenLightOutput = {"PWM3", S.high_light_intensity};          // Green light...
  OutputAction BlueLightOutputBackground = {"PWM4", S.low_light_intensity};  // Blue light Background...
  OutputAction RedLightOutputBackground = {"PWM2", S.low_light_intensity};   // red light Background...
  OutputAction GreenLightOutputBackground = {"PWM3", S.low_light_intensity}; // Green light Background...

  // light intensity
  OutputAction LeftLightOutputH = {"PWM1", S.high_light_intensity};  // High left light intensity
  OutputAction RightLightOutputH = {"PWM5", S.high_light_intensity}; // High right light intensity

  /*******************************************************/

  smart.EmptyMatrix(); // clear matrix at the begining of each trial

  switch (S.currProtocolIndex)
  {  // no earlylick punishment
  // Habitation 学习触发 中间水嘴来开启一个 trial free reward(100% 有free reward：随机出现在左右);   
  // trigger-fixation-period（100ms -> 500ms）+ sample period (100 -> 500ms) + delay period(10~200ms randomly) + Cue(100ms, 3KHz): 
  // 5 steps (100% free reward, [Earlylick < 20 advanced])
  
  // DelayPeriod 10 ms; S.PreCueDelayPeriod 10 ms ; 如果连续三个trial是 EL， 下一个trial 只需要EL inhibit 第一个 block delay
  case 0: // 10 ms + 10ms sample period; EL timeout: 2s  // 10 ms EL Inhibitation
  case 1: // 10 ms + 100ms EL timeout: Beta 3s  // overal 10 + (50 + 50, Onset Trials) + 6 + 10 + 100 + 10 = 136 ms (236 ms in the onset)
  case 2: // 50 ms + 200ms EL timeout: Beta 4s  // 236 + 40 + 100 == 276 ms
  case 3: // 100 ms + 400ms EL timeout: Beta 5s  // 276 + 50 + 200 == 526 ms
  // Pre-Ex: DelayPeriod 50~100 ms S.PreCueDelayPeriod 100 ms
  case 4: // 200 ms + 500ms EL timeout: Beta 6s  // 526 + 100 + 100 + 100 + 100 = 926 ms
  {   
    S.TimeOut = exponent(S.currProtocolIndex+2, 2 ,9);
    
    if(S.currProtocolIndex < 4){
      S.DelayPeriod = 10;
      S.PreCueDelayPeriod = 10;
      S.reward_middle = 100 - S.currProtocolIndex * 20;
      
      if(S.currProtocolIndex == 0){
        EL_Favor = 0;
        S.TimeOut = 2000;
       }   
    }else{
      S.DelayPeriod = int(random(50, 100));
      S.PreCueDelayPeriod = 100;
      S.reward_middle = S.reward_left;
    }
    
    float reward_dur = S.reward_left;

    OutputAction SampleOutput; // top buzzer
    OutputAction RewardOutput;

    String LeftLickAction;
    String RightLickAction;
    String ActionAfterDelay;
    String TrialBeignState;
    String TrialBlockOnsetEL;

    // 根据 currstimu 来决定 sample output stimu1 为 freq low -1 high 1 ； stimu2 spatial left -1 right 1
    if(currStimu[0] == -1){ // left orientation
      switch (int(currStimu[1] * 2))
      {
      case -2: // left low
        SampleOutput = LeftLowSoundOutput;
        break;
      case -1: // left low mid
        SampleOutput = LeftLowMidSoundOutput;
        break;
      case 0: // left mid
        SampleOutput = LeftCueSoundOutput;
        break;
      case 1: // left high mid
        SampleOutput = LeftHighMidSoundOutput;
        break;
      case 2: // left high
        SampleOutput = LeftHighSoundOutput;
        break;
      default:
        break;
      }
    }else if(currStimu[0] == 1){ // right orientation
      switch (int(currStimu[1] * 2))
      {
      case -2: // right low
        SampleOutput = RightLowSoundOutput;
        break;
      case -1: // right low mid
        SampleOutput = RightLowMidSoundOutput;
        break;
      case 0: // right mid
        SampleOutput = RightCueSoundOutput;
        break;
      case 1: // right high mid
        SampleOutput = RightHighMidSoundOutput;
        break;
      case 2: // right high
        SampleOutput = RightHighSoundOutput;
        break;
      default:
        break;
      }
    }

    switch (TrialType)
    {
    case 1: // left choice ; 3khz 
    {
      LeftLickAction = "Reward";
      RightLickAction = "AnswerPeriod"; 
  
      RewardOutput = LeftWaterOutput;
      reward_dur = S.reward_left;
    }
      break;
    case 2: // right choice ; 12khz
    {
      LeftLickAction = "AnswerPeriod"; 
      RightLickAction = "Reward";

      RewardOutput = RightWaterOutput;
      reward_dur = S.reward_right;
    }
      break;
    } 
  
    if (int(random(100)) < (100 - 15 * S.currProtocolIndex))
    { // free reward probability
      ActionAfterDelay = "GiveFreeDrop";
    }
    else
    {
      ActionAfterDelay = "Cue";
    }

    // for time alignment
   if(TrialBlockOnset){// trial block onset
    TrialBeignState = "NeuralReader";
    TrialBlockOnsetEL = "TrialBlockEnd";
    TrialBlockOnset = 0;
   }else{ // within one trial block
    TrialBeignState = "TrialStart";
    TrialBlockOnsetEL = "ReturnInitFixation";
   }
  

    /*******************************************************State Machine HABITS******************************************************************    */   
    StateTransition TrialBlockDelay_Cond[2] = {{"Tup", TrialBeignState}, {"DI1Rising" ,TrialBlockOnsetEL}}; 
    StateTransition ReturnInitFixation_Cond[4] = {{"Tup", "EarlyLickAborted"}, {"DI1Falling" ,"TrialBlockDelay"}, {"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}}; 
    StateTransition NeuralReader_Cond[1] = {{"Tup", "CapReinit"}}; 
    StateTransition CapReinit_Cond[1] = {{"Tup", "TrialStart"}}; 
    StateTransition TrialStart_Cond[1] = {{"Tup", "PreCueDelayPeriod"}}; 
    StateTransition PreCueDelayPeriod_Cond[3] = {{"Tup", "SampleCue"} ,{"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}};
    StateTransition EarlyLickAborted_Cond[1] = {{"Tup" , "TimeOutEL"}};
    StateTransition DelayPeriod_Cond[3]   = {{"Tup", ActionAfterDelay} ,{"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}};
    StateTransition TrialEnd_Cond[2] = {{"Tup", "TrialBlockEnd"} ,{"DI1Falling" ,"exit"}};
    StateTransition GiveFreeDrop_Cond[1] = {{"Tup", "Cue"}};
    StateTransition AnswerPeriod_Cond[3] = {{"Lick1In", LeftLickAction}, {"Lick2In", RightLickAction}, {"Tup", "NoResponse"}};
    StateTransition Reward_Cond[1] = {{"Tup", "RewardConsumption"}};
    StateTransition Tup_Exit_Cond[1] = {{"Tup", "Fixed_ITI"}};
    StateTransition ErrorTrial_Cond[1] = {{"Tup", "exit"}};
    StateTransition Fixed_ITI_Return_Cond[1] = {{"Tup" , "Fixed_ITI"}};
    StateTransition SampleCue_Cond[3]   = {{"Tup","DelayPeriod" }, {"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}};
    StateTransition Cue_Cond[1]     = {{"Tup" , "AnswerPeriod"}};
    StateTransition NoResponse_Cond[1] = {{"Tup", "TrialEnd"}};
    StateTransition TrialBlockEnd_Cond[2] = {{"Tup", "exit"}, {"DI1Falling" ,"exit"}};
    StateTransition Fixed_ITI_Cond[3] = {{"Tup", "TrialEnd"}, {"Lick1In", "Fixed_ITI_Return"}, {"Lick2In", "Fixed_ITI_Return"}};

    OutputAction NeuralReader_Output[1] = {SpikeRecordingOutput};
    OutputAction CapReinit_Output[1] = {CapReinitOutput};
    OutputAction TrialStart_Output[1] = {TimeAlignmentOutput};
    OutputAction Sample_Output[1]     	   = {SampleOutput};
    OutputAction Reward_Output[1] = {RewardOutput};
    OutputAction FreeReward_Output[1] = {RewardOutput};
    OutputAction NoOutput[0] = {};
    OutputAction ErrorOutput[2] = {NoiseOutput, Inavailable_Output};
    OutputAction EndCue_Output[1]      = {CueOutput};
    OutputAction TrialEnd_Output[1] = {smartFinish_Output};
    OutputAction TrialBlockEnd_Output[3] = {Inactive_Output, LFPRecordingOutput, CapDisableOutput};
    OutputAction TimeOut_Output[1] = {Inavailable_Output};

    gpSMART_State states[21] = {};
    // visual flash states and conditions
    states[0] = smart.CreateState("TrialBlockDelay",                 S.TrialBlockInitPeriod,    2,                  TrialBlockDelay_Cond,         0,           NoOutput); // remove trial initiation without engagement
    states[20] = smart.CreateState("ReturnInitFixation",             100,                       4,                  ReturnInitFixation_Cond,      0,           NoOutput); // avoid mis-detection of fixed action or give mice the second chance to re-fix.
    states[18] = smart.CreateState("NeuralReader",                   50,                        1,                  NeuralReader_Cond,            1,           NeuralReader_Output); 
    states[19] = smart.CreateState("CapReinit",                      50,                        1,                  CapReinit_Cond,               1,           CapReinit_Output); 
    
    states[15] = smart.CreateState("TrialStart",                     6,                         1,                  TrialStart_Cond,              1,           TrialStart_Output); // for time alignment by adding 2Khz signal marker
    states[3] = smart.CreateState("PreCueDelayPeriod",               S.PreCueDelayPeriod,       1+EL_Favor,         PreCueDelayPeriod_Cond,       0,           NoOutput); // for islating the noised alignment signal
    states[11] = smart.CreateState("EarlyLickAborted",               100              ,         1,                  EarlyLickAborted_Cond,        1,           ErrorOutput); 
    states[13] = smart.CreateState("SampleCue",                      S.SamplePeriod,            1+EL_Favor   ,      SampleCue_Cond,               1,           Sample_Output); // 100 ~ 500ms
    states[1] = smart.CreateState("DelayPeriod",                     S.DelayPeriod,             1+EL_Favor,         DelayPeriod_Cond,             0,           NoOutput);
    states[14] = smart.CreateState("Cue",                            100,                       1    ,              Cue_Cond,                     1,           EndCue_Output); 
    states[4] = smart.CreateState("GiveFreeDrop",                    S.reward_middle,           1,                  GiveFreeDrop_Cond,            1,           FreeReward_Output);
    states[5] = smart.CreateState("AnswerPeriod",                    S.AnswerPeriod,            3,                  AnswerPeriod_Cond,            1,           TimeOut_Output);
    states[6] = smart.CreateState("Reward",                          reward_dur,                1,                  Reward_Cond,                  1,           Reward_Output);
    states[7] = smart.CreateState("RewardConsumption",               S.ConsumptionPeriod,       1,                  Tup_Exit_Cond,                1,           TimeOut_Output);
    states[8] = smart.CreateState("NoResponse",                      10                        ,1,                  NoResponse_Cond,              0,           NoOutput);  // enter to the Trial end
    states[9] = smart.CreateState("ErrorTrial",                      500,                       1,                  ErrorTrial_Cond,              2,           ErrorOutput); // not used
    states[10] = smart.CreateState("TimeOutEL",                      S.TimeOut,                 1,                  Tup_Exit_Cond,                1,           TimeOut_Output);
    states[17] = smart.CreateState("Fixed_ITI",                      500       ,                3,                  Fixed_ITI_Cond,               1,           TimeOut_Output); // Fixed 1000 ms ITI without licking
    states[12] = smart.CreateState("Fixed_ITI_Return",               100,                       1,                  Fixed_ITI_Return_Cond,        1,           TimeOut_Output);
    states[2] = smart.CreateState("TrialEnd",                        10000,                     2,                  TrialEnd_Cond,                1,           TrialEnd_Output); // waiting next self-initated trial
    
    states[16] = smart.CreateState("TrialBlockEnd",                 12 * 60 * 60 * 1000,        2,                  TrialBlockEnd_Cond,           3,           TrialBlockEnd_Output);  // TrialBlock end + Serial output for Mode1 open
    
    // Predefine State sequence.
    for (int i = 0; i < 21; i++)
    {
      smart.AddBlankState(states[i].Name);
    }

    // Add a state to state machine.
    for (int i = 0; i < 21; i++)
    {
      smart.AddState(&states[i]);
    }
    // smart.PrintMatrix(); // for debug
    // Run the matrix
    smart.Run();
  }
  break;
  // Loc antibias for training full trial structure
  case 5: // trigger-fixation-period(200ms）+ sample period (500ms fixation) + delay period(200ms) + Cue(100ms): no free reward;  punishment 3000~8000 ms
  case 6: // retention period: delay period (50~200 ms randomly); random trial type with model fitting
  // Freq antibias
  case 7: // freq
  case 8: // freq retention random trial type with model fitting delay period (50~200ms randomly)
  // reversal freq MT antibias
  case 9: // reversal freq
  case 10: // reversal retention random trial type with model fitting delay period (50~200ms randomly)
  {       
    S.DelayPeriod = int(random(50, 200));
    S.TimeOut = exponent(5 ,3 ,8);

    OutputAction SampleOutput; // top buzzer
    OutputAction RewardOutput;
 
    String LeftLickAction;
    String RightLickAction;
    String TrialBeignState;
    String TrialBlockOnsetEL;

    float reward_dur = S.reward_left;

    // 根据 currstimu 来决定 sample output stimu1 为 freq low -1 high 1 ； stimu2 spatial left -1 right 1
    if(currStimu[0] == -1){ // left orientation
      switch (int(currStimu[1] * 2))
      {
      case -2: // left low
        SampleOutput = LeftLowSoundOutput;
        break;
      case -1: // left low mid
        SampleOutput = LeftLowMidSoundOutput;
        break;
      case 0: // left mid
        SampleOutput = LeftCueSoundOutput;
        break;
      case 1: // left high mid
        SampleOutput = LeftHighMidSoundOutput;
        break;
      case 2: // left high
        SampleOutput = LeftHighSoundOutput;
        break;
      default:
        break;
      }
    }else if(currStimu[0] == 1){ // right orientation
      switch (int(currStimu[1] * 2))
      {
      case -2: // right low
        SampleOutput = RightLowSoundOutput;
        break;
      case -1: // right low mid
        SampleOutput = RightLowMidSoundOutput;
        break;
      case 0: // right mid
        SampleOutput = RightCueSoundOutput;
        break;
      case 1: // right high mid
        SampleOutput = RightHighMidSoundOutput;
        break;
      case 2: // right high
        SampleOutput = RightHighSoundOutput;
        break;
      default:
        break;
      }
    }

    switch (TrialType)
    {
    case 1: // left choice ; 3khz 
    {
      LeftLickAction = "Reward";
      RightLickAction = "ErrorTrial"; 

      RewardOutput = LeftWaterOutput;
      reward_dur = S.reward_left;
    }
      break;
    case 2: // right choice ; 12khz
    {
      LeftLickAction = "ErrorTrial"; 
      RightLickAction = "Reward";

      RewardOutput = RightWaterOutput;
      reward_dur = S.reward_right;
    }
      break;
    }

    if(int(random(100)) < CatchTrialProb){
      BaselineTrialFlag = 1;
      SampleOutput = NoSoundOutput;
      LeftLickAction = "RewardConsumption";  // No reward; No stimulus
      RightLickAction = "RewardConsumption";
    }else{
      BaselineTrialFlag = 0;
    }
    // for time alignment
    if(TrialBlockOnset){// trial block onset
      TrialBeignState = "NeuralReader";
      TrialBlockOnsetEL = "TrialBlockEnd";
      TrialBlockOnset = 0;
    }else{ // within one trial block
      TrialBeignState = "TrialStart";
      TrialBlockOnsetEL = "ReturnInitFixation";
    }
    
    StateTransition TrialBlockDelay_Cond[2] = {{"Tup",TrialBeignState},{"DI1Rising", TrialBlockOnsetEL}}; 
    StateTransition ReturnInitFixation_Cond[4] = {{"Tup", "EarlyLickAborted"}, {"DI1Falling" ,"TrialBlockDelay"}, {"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}}; 
    StateTransition NeuralReader_Cond[1] = {{"Tup", "CapReinit"}}; 
    StateTransition CapReinit_Cond[1] = {{"Tup", "TrialStart"}}; 
    StateTransition PreCueDelayPeriod_Cond[3] = {{"Tup", "SampleCue"} ,{"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}};
    StateTransition TrialStart_Cond[1] = {{"Tup", "PreCueDelayPeriod"}}; 
    StateTransition DelayPeriod_Cond[3]   = {{"Tup", "Cue"},{"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}};
    StateTransition TrialEnd_Cond[2] = {{"Tup", "TrialBlockEnd"} ,{"DI1Falling" ,"exit"}};
    StateTransition GiveFreeDrop_Cond[1] = {{"Tup", "DelayPeriod"}};
    StateTransition SampleCue_Cond[3]   = {{"Tup",  "DelayPeriod"},{"Lick1In", "EarlyLickAborted"}, {"Lick2In", "EarlyLickAborted"}};
    StateTransition AnswerPeriod_Cond[3] = {{"Lick1In", LeftLickAction}, {"Lick2In", RightLickAction}, {"Tup", "NoResponse"}};
    StateTransition Reward_Cond[1] = {{"Tup", "RewardConsumption"}};
    StateTransition Tup_Exit_Cond[1] = {{"Tup", "Fixed_ITI"}};
    StateTransition ErrorTrial_Cond[1] = {{"Tup", "TimeOut"}};
    StateTransition Fixed_ITI_Return_Cond[1] = {{"Tup" , "Fixed_ITI"}};
    StateTransition ErrorTest_Cond[1]     = {{"Tup" , "AnswerPeriod"}};
    StateTransition Cue_Cond[1]     = {{"Tup" , "AnswerPeriod"}};
    StateTransition NoResponse_Cond[1] = {{"Tup", "TrialEnd"}};
    StateTransition TrialBlockEnd_Cond[2] = {{"Tup", "exit"}, {"DI1Falling" ,"exit"}};
    StateTransition Fixed_ITI_Cond[3] = {{"Tup", "TrialEnd"}, {"Lick1In", "Fixed_ITI_Return"}, {"Lick2In", "Fixed_ITI_Return"}};
    
    StateTransition EarlyLickAborted_Cond[1] = {{"Tup" , "TimeOutEL"}};
    StateTransition Tup_StopLicking_Cond[1] = {{"Tup", "StopLicking"}};
    StateTransition StopLicking_Cond[3] = {{"Lick1In", "StopLickingReturn"}, {"Lick2In", "StopLickingReturn"} , {"Tup", "Fixed_ITI"}}; 
    
    OutputAction NeuralReader_Output[1] = {SpikeRecordingOutput};
    OutputAction CapReinit_Output[1] = {CapReinitOutput};
    OutputAction Sample_Output[1]     	   = {SampleOutput};
    OutputAction Reward_Output[1] = {RewardOutput};
    OutputAction FreeReward_Output[1] = {RewardOutput};
    OutputAction NoOutput[0] = {};
    OutputAction ErrorOutput[2] = {NoiseOutput, Inavailable_Output};
    OutputAction EndCue_Output[1]      = {CueOutput};
    OutputAction TrialStart_Output[1] = {TimeAlignmentOutput};
    OutputAction TrialEnd_Output[1] = {smartFinish_Output};
    OutputAction TrialBlockEnd_Output[3] = {Inactive_Output, LFPRecordingOutput, CapDisableOutput};
    OutputAction TimeOut_Output[1] = {Inavailable_Output};

    gpSMART_State states[26] = {};
    // visual flash states and conditions
    states[0] = smart.CreateState("TrialBlockDelay",                 S.TrialBlockInitPeriod,    2,                  TrialBlockDelay_Cond,         0,           NoOutput); // 
    states[25] = smart.CreateState("ReturnInitFixation",             100,                       4,                  ReturnInitFixation_Cond,      0,           NoOutput); // avoid mis-detection of fixed action or give mice the second chance to re-fix.
    states[23] = smart.CreateState("NeuralReader",                   50,                        1,                  NeuralReader_Cond,            1,           NeuralReader_Output); 
    states[24] = smart.CreateState("CapReinit",                      50,                        1,                  CapReinit_Cond,               1,           CapReinit_Output); 

    states[20] = smart.CreateState("TrialStart",                     6,                         1,                  TrialStart_Cond,              1,           TrialStart_Output); // msec
    states[3] = smart.CreateState("PreCueDelayPeriod",               100,                       1+EL_Favor        , PreCueDelayPeriod_Cond,       0,           NoOutput);
    states[11] = smart.CreateState("EarlyLickAborted",               100              ,         1,                  EarlyLickAborted_Cond,        1,           ErrorOutput); 
    states[16] = smart.CreateState("SampleCue",                      S.SamplePeriod,            1+EL_Favor        , SampleCue_Cond,               1,           Sample_Output); // 500ms
    states[1] = smart.CreateState("DelayPeriod",                     S.DelayPeriod,             1+EL_Favor ,        DelayPeriod_Cond,             0,           NoOutput);
    states[18] = smart.CreateState("Cue",                            100,                       1    ,              Cue_Cond,                     1,           EndCue_Output);
    states[4] = smart.CreateState("GiveFreeDrop",                    reward_dur,                1,                  GiveFreeDrop_Cond,            1,           FreeReward_Output); // not used
    states[5] = smart.CreateState("AnswerPeriod",                    S.AnswerPeriod,            3,                  AnswerPeriod_Cond,            1,           TimeOut_Output);
    states[6] = smart.CreateState("Reward",                          reward_dur,                1,                  Reward_Cond,                  1,           Reward_Output);
    states[7] = smart.CreateState("RewardConsumption",               S.ConsumptionPeriod,       1,                  Tup_StopLicking_Cond,         1,           TimeOut_Output);
    states[14] = smart.CreateState("StopLicking",                    S.StopLickingPeriod,       3,                  StopLicking_Cond,             1,           TimeOut_Output);
    states[15] = smart.CreateState("StopLickingReturn",              100,                       1,                  Tup_StopLicking_Cond,         1,           TimeOut_Output);
    states[8] = smart.CreateState("NoResponse",                      10                        ,1,                  NoResponse_Cond,              0,           NoOutput); 
    states[9] = smart.CreateState("ErrorTrial",                      500,                       1,                  ErrorTrial_Cond,              2,           ErrorOutput); 
    states[17] = smart.CreateState("ErrorTest",                      10,                        1,                  ErrorTest_Cond,               0,           NoOutput);  // not used
    states[13] = smart.CreateState("TimeOut",                        S.TimeOut+S.extra_TimeOut, 1,                  Tup_Exit_Cond,                1,           TimeOut_Output);
    states[10] = smart.CreateState("TimeOutEL",                      exponent(6 ,5 ,9),         1,                  Tup_Exit_Cond,                1,           TimeOut_Output);
    states[22] = smart.CreateState("Fixed_ITI",                      1000       ,               3,                  Fixed_ITI_Cond,               1,           TimeOut_Output); // Fixed 1000 ms ITI without licking
    states[12] = smart.CreateState("Fixed_ITI_Return",               100,                       1,                  Fixed_ITI_Return_Cond,        1,           TimeOut_Output);
    states[2] = smart.CreateState("TrialEnd",                        10000            ,         2,                  TrialEnd_Cond,                1,           TrialEnd_Output);

    states[21] = smart.CreateState("TrialBlockEnd",                  12 * 60 * 60 * 1000,       2,                  TrialBlockEnd_Cond,           3,           TrialBlockEnd_Output);  // TrialBlock end + Serial output for Mode1 open
    // Predefine State sequence.
    for (int i = 0; i < 26; i++)
    {
      smart.AddBlankState(states[i].Name);
    }

    // Add a state to state machine.
    for (int i = 0; i < 26; i++)
    {
      smart.AddState(&states[i]);
    }
    // smart.PrintMatrix(); // for debug
    // Run the matrix
    smart.Run();
  }
  break;
  default:
    break;
  } // end for Switch(protocol)
}

void UpdateTrialOutcome()
{
  /* data will be stored in public variable 'trial_res', which includes:
    trial_res.nEvent:           number of event happened in last trial
    trial_res.eventTimeStamps[]: time stamps for each event
    trial_res.EventID[]:          event id for each event
    trial_res.nVisited:       number of states visited in last trial
    trial_res.stateVisited[]:   the states visited in last trail
  */

  TrialOutcome = 3; // 0 no-response; 1 correct; 2 error; 3 others
  int ErrorState = 9;

  for (int i = 0; i < trial_res.nVisited; i++)
  {
    if (trial_res.stateVisited[i] == 6 || trial_res.stateVisited[i] == 8 || trial_res.stateVisited[i] == ErrorState)
    { // Reward || No Response || Error

      if (trial_res.stateVisited[i] == 6)
      {
        TrialOutcome = 1;
      }
      else if (trial_res.stateVisited[i] == 8)
      {
        TrialOutcome = 0;
      }
      else
      {
        TrialOutcome = 2;
      }
      break;
    }
  }

  if (TrialOutcome == 1)
  {
    S.totalRewardNum++;
    last_reward_time = millis(); // record the last reward time
    timed_reward_count = 0;
  }

  is_earlylick = 2;
  if (S.currProtocolIndex >= 0) 
  {
    is_earlylick = 0;
    for (int i = 0; i < trial_res.nVisited; i++)
    {
      if (trial_res.stateVisited[i] == 11)
      { // earlylick delay
        is_earlylick = 1;
        break;
      }
    }
  }

  // do FIFO
  for (int i = 0; i < RECORD_TRIALS - 1; i++)
  {
    S.ProtocolIndexHistory[i] = S.ProtocolIndexHistory[i + 1];
    S.TrialTypeHistory[i] = S.TrialTypeHistory[i + 1]; //
    S.Stimu1History[i] = S.Stimu1History[i + 1];
    S.Stimu2History[i] = S.Stimu2History[i + 1];
    S.OutcomeHistory[i] = S.OutcomeHistory[i + 1];     //
    S.SampleTypeHistory[i] = S.SampleTypeHistory[i + 1];     
    S.EarlyLickHistory[i] = S.EarlyLickHistory[i + 1]; //
  }
  // Keep record current trial info in the last position (RECORD_TRIALS-1) of the matrix
  S.ProtocolIndexHistory[RECORD_TRIALS - 1] = S.currProtocolIndex;
  S.OutcomeHistory[RECORD_TRIALS - 1] = TrialOutcome;
  S.TrialTypeHistory[RECORD_TRIALS - 1] = TrialType;
  S.Stimu1History[RECORD_TRIALS - 1] = int((currStimu[0] * 2) + 2);// 0~4 -> -1 -> 1
  S.Stimu2History[RECORD_TRIALS - 1] = int((currStimu[1] * 2) + 2);
  S.EarlyLickHistory[RECORD_TRIALS - 1] = is_earlylick;
  S.SampleTypeHistory[RECORD_TRIALS - 1] = SampleType;

  byte Outcomes_sum = 0;
  for (int i = RECORD_TRIALS - recent_trials; i < RECORD_TRIALS; i++)
  {
    if (S.OutcomeHistory[i] == 1)
    {
      Outcomes_sum++;
    }
  }

  // EMA S.currProtocolPerf ; alpha is 0.02 ; 50 trials average
  float CurrOutcome = 0;
  // recording the last valid trial
  if (S.OutcomeHistory[RECORD_TRIALS - 1] != 3 && S.OutcomeHistory[RECORD_TRIALS - 1] != 0)
  {
    S.currProtocolTrials++;
    if (S.OutcomeHistory[RECORD_TRIALS - 1] == 1)
    {
      CurrOutcome = 1.0;
    }
    else if (S.OutcomeHistory[RECORD_TRIALS - 1] == 2)
    {
      CurrOutcome = 0.0;
    }
    S.currProtocolPerf = S.currProtocolPerf * Alpha500 + (1.0 - Alpha500) * CurrOutcome;
  }
  currProtocolPerf_corrected = S.currProtocolPerf / (1.0 - pow(Alpha500 ,S.currProtocolTrials));

  Perf100 = 0;
  EarlyLick100 = 0;
  for (int i = 0; i < RECORD_TRIALS; i++)
  {
    if (S.OutcomeHistory[i] == 1)
    {
      Perf100++;
    }
    if (S.EarlyLickHistory[i] == 1)
    {
      EarlyLick100++;
    }
  }
}

void SendTrialInfo2PC()
{
  String TrialInfo_str = "T";

  TrialInfo_str += String(S.currTrialNum);
  TrialInfo_str += ",";

  TrialInfo_str += String(TrialType);
  TrialInfo_str += ",";

  TrialInfo_str += String(S.currProtocolIndex);
  TrialInfo_str += ",";

  TrialInfo_str += String(TrialOutcome);
  TrialInfo_str += ",";

  TrialInfo_str += String(EarlyLick100);
  TrialInfo_str += ",";

  TrialInfo_str += String(Perf100);
  TrialInfo_str += ",";

  TrialInfo_str += String(S.currProtocolTrials);
  TrialInfo_str += ",";

  TrialInfo_str += String(int(currProtocolPerf_corrected * 100));
  TrialInfo_str += ",";

  TrialInfo_str.toCharArray(outBuffer, 255);
  Serial.println(outBuffer);
}

void autoChangeProtocol()
{ 
  switch (S.currProtocolIndex)
  {
  case 0: // habitation 1
   if (S.currProtocolTrials > 100 && EarlyLick100 < 20)
//      if (S.currProtocolTrials > 10)
    {                        
      S.currProtocolIndex = 1; // habitation 2
      S.currProtocolTrials = 0;
      S.currProtocolPerf = 0;

      S.TrialBlockInitPeriod = 10;
      S.SamplePeriod = 100;
      S.TimeOut = 3000;
      S.AnswerPeriod = 10000;
      S.ConsumptionPeriod = 750;
      S.StopLickingPeriod   = 400;
      S.rule = 0; // aud loaction
      S.TrialPresentMode = 0; // random 
    }
    break;
    
  case 1: // habitation 2
   if (S.currProtocolTrials > 100 && EarlyLick100 < 20)
//      if (S.currProtocolTrials > 10)
    {
      S.currProtocolIndex = 2; // habitation 3
      S.currProtocolTrials = 0;
      S.currProtocolPerf = 0;

      S.TrialBlockInitPeriod = 50;
      S.SamplePeriod = 200;
      S.TimeOut = 4000;
      S.AnswerPeriod = 10000;
      S.ConsumptionPeriod = 750;
      S.StopLickingPeriod   = 400;
      S.rule = 0; // aud loaction
      S.TrialPresentMode = 0;  // random 
    }
    break;

  case 2: // habitation 3
   if (S.currProtocolTrials > 100 && EarlyLick100 < 25)
//      if (S.currProtocolTrials > 10)
    {                        
      S.currProtocolIndex = 3; // habitation 4
      S.currProtocolTrials = 0;
      S.currProtocolPerf = 0;

      S.TrialBlockInitPeriod = 100;
      S.SamplePeriod = 400;
      S.TimeOut = 5000;
      S.AnswerPeriod = 10000;
      S.ConsumptionPeriod = 750;
      S.StopLickingPeriod   = 400;
      S.rule = 0; // aud loaction
      S.TrialPresentMode = 0; // random 
    }
    break;
  
  case 3: // habitation 
 if (S.currProtocolTrials > 100 && EarlyLick100 < 30)
//    if (S.currProtocolTrials > 10)
  {                        
    S.currProtocolIndex = 4; // habitation 5
    S.currProtocolTrials = 0;
    S.currProtocolPerf = 0;

    S.TrialBlockInitPeriod = 200;
    S.SamplePeriod = 500;
    S.TimeOut = 6000;
    S.AnswerPeriod = 10000;
    S.ConsumptionPeriod = 750;
    S.StopLickingPeriod   = 400;
    S.rule = 0; // aud loaction
    S.TrialPresentMode = 0; // random 
  }
  break;

  case 4: // habitation 
 if (S.currProtocolTrials > 100 && EarlyLick100 < 40)
//    if (S.currProtocolTrials > 10)
  {                        
    S.currProtocolIndex = 5; // Early training loc
    S.currProtocolTrials = 0;
    S.currProtocolPerf = 0;

    S.TrialBlockInitPeriod = 200;
    S.SamplePeriod = 500;
    S.DelayPeriod = 200;
    S.AnswerPeriod = 5000;
    S.ConsumptionPeriod = 750;
    S.StopLickingPeriod   = 400;
    S.rule = 0; // aud loaction
    S.TrialPresentMode = 1; // antibias
  }
  break;




  case 5: // loc 
  if (S.currProtocolTrials >= 500 && int(currProtocolPerf_corrected * 100) >= 75)
//      if (S.currProtocolTrials > 10)
    {
      S.currProtocolTrials = 0;
      S.currProtocolPerf = 0;
      S.currProtocolIndex = 6; // retention
      S.rule = 0; 

      S.TrialBlockInitPeriod = 200;
      S.SamplePeriod = 500;
      S.DelayPeriod = 200;
      S.AnswerPeriod = 5000;
      S.ConsumptionPeriod = 750;
      S.StopLickingPeriod = 400;
      S.TrialPresentMode = 0;  // random
    }
    break;
  
  case 6: // loc retention
 if (S.currProtocolTrials >= 1000 && Perf100 > 75)
//    if (S.currProtocolTrials > 10)
  {
    S.currProtocolTrials = 0;
    S.currProtocolPerf = 0;
    S.currProtocolIndex = 7;
    S.rule = 1;  // aud freq

    S.TrialBlockInitPeriod = 200;
    S.SamplePeriod = 500;
    S.DelayPeriod = 200;
    S.AnswerPeriod = 5000;
    S.ConsumptionPeriod = 750;
    S.StopLickingPeriod = 400;
    S.TrialPresentMode = 1;  //antibias
  }
  break;





  case 7: // aud freq
  if (S.currProtocolTrials >= 500 && int(currProtocolPerf_corrected * 100) >= 70)
//    if (S.currProtocolTrials > 10)
    {
      S.rule = 1; //  aud freq retention
      S.currProtocolIndex = 8;
      S.currProtocolPerf = 0;
      S.currProtocolTrials = 0;

      S.TrialBlockInitPeriod = 200;
      S.SamplePeriod = 500;
      S.DelayPeriod = 200;
      S.AnswerPeriod = 5000;
      S.ConsumptionPeriod = 750;
      S.StopLickingPeriod = 400;
      S.TrialPresentMode = 0;  // random
    }
    break;

  case 8: // aud freq retention
   if (S.currProtocolTrials >= 1000 && Perf100 > 70)
//      if (S.currProtocolTrials > 10)
    {
      S.currProtocolTrials = 0;
      S.currProtocolPerf = 0;
      S.currProtocolIndex = 9;
      S.rule = 2;  // aud freq reversal

      S.TrialBlockInitPeriod = 200;
      S.SamplePeriod = 500;
      S.DelayPeriod = 200;
      S.AnswerPeriod = 5000;
      S.ConsumptionPeriod = 750;
      S.StopLickingPeriod = 400;
      S.TrialPresentMode = 1;  // antibias
    }
    break;







  case 9: // aud freq reversal
  if (S.currProtocolTrials >= 500 && int(currProtocolPerf_corrected * 100) >= 70)
// if (S.currProtocolTrials > 10)
    {
      S.rule = 2; //  aud freq reversal
      S.currProtocolIndex = 10; // retention reversal aud freq
      S.currProtocolPerf = 0;
      S.currProtocolTrials = 0;

      S.TrialBlockInitPeriod = 200;
      S.SamplePeriod = 500;
      S.DelayPeriod = 200;
      S.AnswerPeriod = 5000;
      S.ConsumptionPeriod = 750;
      S.StopLickingPeriod = 400;
      S.TrialPresentMode = 0;  // random
    }
    break;
    default:
    break;
  }
}

void autoReward()
{
  S.GaveFreeReward.past_trials++;
  byte error_trials = 3; // consecutive 3 errors in a paticular trial type => free reward in next trial
  if (S.GaveFreeReward.past_trials >= error_trials)
  {
    byte n_RSideErrors = 0;
    byte n_LSideErrors = 0;
    for (int i = 0; i < error_trials; i++)
    {
      if (S.TrialTypeHistory[RECORD_TRIALS - error_trials + i] == 2 && S.OutcomeHistory[RECORD_TRIALS - error_trials + i] != 1)
      {
        n_RSideErrors++;
      }
      else if (S.TrialTypeHistory[RECORD_TRIALS - error_trials + i] == 1 && S.OutcomeHistory[RECORD_TRIALS - error_trials + i] != 1)
      {
        n_LSideErrors++;
      }
    }
    if (n_RSideErrors == error_trials)
    {
      S.GaveFreeReward.flag_R_water = 1;
      S.GaveFreeReward.flag_L_water = 0;
      S.GaveFreeReward.past_trials = 0;
    }
    else if (n_LSideErrors == error_trials)
    {
      S.GaveFreeReward.flag_R_water = 0;
      S.GaveFreeReward.flag_L_water = 1;
      S.GaveFreeReward.past_trials = 0;
    }
  }
}

void trialSelection() { // 
  switch (S.TrialPresentMode) {
    case 0: // random 
    {
      currStimu[0] = S1Feat[int(random(0 ,2))];
      currStimu[1] = S2Feat[int(random(0 ,5))];
      rule_define(S.rule ,currStimu[0] ,currStimu[1]);
    }
    break;
    case 1: // antibias 75% copy the easiest trial which is error at the last 1 trial
    {
      int antibias_randn = int(random(0 ,100));
      if(S.OutcomeHistory[RECORD_TRIALS - 1] != 1 && S.SampleTypeHistory[RECORD_TRIALS - 1] == 2 && antibias_randn < 60) //TODO 60% easiest trial type
      {
        // keep last params of trial
      }else{
        currStimu[0] = S1Feat[int(random(0 ,2))];
        currStimu[1] = S2Feat[int(random(0 ,5))];
      }
      rule_define(S.rule ,currStimu[0] ,currStimu[1]);
    }
    break;
    default:
    break;
  }
  // Earlylick favor trials
  int switch_indicator = 0;
  for (int i = RECORD_TRIALS - 1; i >= 0; i--) {
    if (S.OutcomeHistory[i] == S.OutcomeHistory[RECORD_TRIALS - 1] && S.OutcomeHistory[i] == 3) {
        switch_indicator++;
    } else {
      break;
    }
  }
  if (switch_indicator >= MaxSame) {
    // 连续三次 earlylick
    EL_Favor = 0; // do a favor trial
  } else{
    EL_Favor = 2;
  }
}

/**************************************************************************************************************/
/********************************************** SD related Functions *******************************************/
/**************************************************************************************************************/
int write_SD_para_S()
{
  File dataFile = SD.open("paraS.txt", FILE_WRITE_BEGIN);
  if (dataFile)
  {
    // currTrialNum
    dataFile.print("currTrialNum = ");
    dataFile.println(S.currTrialNum);
    // currProtocolIndex
    dataFile.print("currProtocolIndex = ");
    dataFile.println(S.currProtocolIndex);
    // currProtocolTrials
    dataFile.print("currProtocolTrials = ");
    dataFile.println(S.currProtocolTrials);
    // currProtocolPerf
    dataFile.print("currProtocolPerf = ");
    dataFile.println(S.currProtocolPerf ,4);
    // TrialPresentMode
    dataFile.print("TrialPresentMode = ");
    dataFile.println(S.TrialPresentMode);
    // ProtocolIndexHistory
    dataFile.print("ProtocolIndexHistory = ");
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      dataFile.print(S.ProtocolIndexHistory[i]);
      dataFile.print("; ");
    }
    dataFile.println();
    // TrialTypeHistory
    dataFile.print("TrialTypeHistory = ");
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      dataFile.print(S.TrialTypeHistory[i]);
      dataFile.print("; ");
    }
    dataFile.println();
    // OutcomeHistory
    dataFile.print("OutcomeHistory = ");
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      dataFile.print(S.OutcomeHistory[i]);
      dataFile.print("; ");
    }
    dataFile.println();

    // EarlyLickHistory
    dataFile.print("EarlyLickHistory = ");
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      dataFile.print(S.EarlyLickHistory[i]);
      dataFile.print("; ");
    }
    dataFile.println();

    // Stimu1History
    dataFile.print("Stimu1History = ");
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      dataFile.print(S.Stimu1History[i]);
      dataFile.print("; ");
    }
    dataFile.println();

    // Stimu2History
    dataFile.print("Stimu2History = ");
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      dataFile.print(S.Stimu2History[i]);
      dataFile.print("; ");
    }
    dataFile.println();

    // SampleTypeHistory
    dataFile.print("SampleTypeHistory = ");
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      dataFile.print(S.SampleTypeHistory[i]);
      dataFile.print("; ");
    }
    dataFile.println();

    // totalRewardNum
    dataFile.print("totalRewardNum = ");
    dataFile.println(S.totalRewardNum);
    // reward_left
    dataFile.print("reward_left = ");
    dataFile.println(S.reward_left);
    // reward_right
    dataFile.print("reward_right = ");
    dataFile.println(S.reward_right);
    // reward_middle
    dataFile.print("reward_middle = ");
    dataFile.println(S.reward_middle);
    // GaveFreeReward
    dataFile.print("GaveFreeReward.flag_L_water = ");
    dataFile.println(S.GaveFreeReward.flag_L_water);
    dataFile.print("GaveFreeReward.flag_R_water = ");
    dataFile.println(S.GaveFreeReward.flag_R_water);
    dataFile.print("GaveFreeReward.flag_M_water = ");
    dataFile.println(S.GaveFreeReward.flag_M_water);
    dataFile.print("GaveFreeReward.past_trials = ");
    dataFile.println(S.GaveFreeReward.past_trials);

    // TrialBlockInitPeriod
    dataFile.print("TrialBlockInitPeriod = ");
    dataFile.println(S.TrialBlockInitPeriod);
    // SamplePeriod
    dataFile.print("SamplePeriod = ");
    dataFile.println(S.SamplePeriod);
    // DelayPeriod
    dataFile.print("DelayPeriod = ");
    dataFile.println(S.DelayPeriod);
    // TimeOut
    dataFile.print("TimeOut = ");
    dataFile.println(S.TimeOut);
    // AnswerPeriod
    dataFile.print("AnswerPeriod = ");
    dataFile.println(S.AnswerPeriod);
    // ConsumptionPeriod
    dataFile.print("ConsumptionPeriod = ");
    dataFile.println(S.ConsumptionPeriod);
    // StopLickingPeriod
    dataFile.print("StopLickingPeriod = ");
    dataFile.println(S.StopLickingPeriod);
    // EarlyLickPeriod
    dataFile.print("EarlyLickPeriod = ");
    dataFile.println(S.EarlyLickPeriod);
    // retention_counter
    dataFile.print("retention_counter = ");
    dataFile.println(S.retention_counter);
    // low_light_intensity
    dataFile.print("low_light_intensity = ");
    dataFile.println(S.low_light_intensity);
    // high_light_intensity
    dataFile.print("high_light_intensity = ");
    dataFile.println(S.high_light_intensity);
    // extra_TimeOut
    dataFile.print("extra_TimeOut = ");
    dataFile.println(S.extra_TimeOut);
    // Trial_txt_position
    dataFile.print("Trial_txt_position = ");
    dataFile.println(S.Trial_txt_position);
    // Tevent_txt_position
    dataFile.print("Tevent_txt_position = ");
    dataFile.println(S.Tevent_txt_position);
    // PreCueDelayPeriod
    dataFile.print("PreCueDelayPeriod = ");
    dataFile.println(S.PreCueDelayPeriod);
    // PreCuePeriod
    dataFile.print("PreCuePeriod = ");
    dataFile.println(S.PreCuePeriod);
    // hardestTrials
    dataFile.print("hardestTrials = ");
    dataFile.println(S.hardestTrials);
    // rule
    dataFile.print("rule = ");
    dataFile.println(S.rule);

  }
  else
  {
    Serial.println("E: error opening paraS.txt for write");
    dataFile.close();
    return -1;
  }
  dataFile.close();
  return 0;
}

int read_SD_para_S()
{
  File dataFile = SD.open("paraS.txt", FILE_READ);
  if (dataFile)
  {
    // currTrialNum
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.currTrialNum = string_tmp.toInt();
    // currProtocolIndex
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.currProtocolIndex = string_tmp.toInt();
    // currProtocolTrials
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.currProtocolTrials = string_tmp.toInt();
    // currProtocolPerf
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.currProtocolPerf = string_tmp.toFloat();
    // TrialPresentMode
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.TrialPresentMode = string_tmp.toInt();
    // ProtocolIndexHistory
    string_tmp = dataFile.readStringUntil('=');
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      string_tmp = dataFile.readStringUntil(';');
      S.ProtocolIndexHistory[i] = string_tmp.toInt();
    }
    string_tmp = dataFile.readStringUntil('\n');
    // TrialTypeHistory
    string_tmp = dataFile.readStringUntil('=');
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      string_tmp = dataFile.readStringUntil(';');
      S.TrialTypeHistory[i] = string_tmp.toInt();
    }
    string_tmp = dataFile.readStringUntil('\n');
    // OutcomeHistory
    string_tmp = dataFile.readStringUntil('=');
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      string_tmp = dataFile.readStringUntil(';');
      S.OutcomeHistory[i] = string_tmp.toInt();
    }
    string_tmp = dataFile.readStringUntil('\n');
    // EarlyLickHistory
    string_tmp = dataFile.readStringUntil('=');
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      string_tmp = dataFile.readStringUntil(';');
      S.EarlyLickHistory[i] = string_tmp.toInt();
    }
    string_tmp = dataFile.readStringUntil('\n');

    // Stimu1History
    string_tmp = dataFile.readStringUntil('=');
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      string_tmp = dataFile.readStringUntil(';');
      S.Stimu1History[i] = string_tmp.toInt();
    }
    string_tmp = dataFile.readStringUntil('\n');

    // Stimu2History
    string_tmp = dataFile.readStringUntil('=');
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      string_tmp = dataFile.readStringUntil(';');
      S.Stimu2History[i] = string_tmp.toInt();
    }
    string_tmp = dataFile.readStringUntil('\n');

    // SampleTypeHistory
    string_tmp = dataFile.readStringUntil('=');
    for (int i = 0; i < RECORD_TRIALS; i++)
    {
      string_tmp = dataFile.readStringUntil(';');
      S.SampleTypeHistory[i] = string_tmp.toInt();
    }
    string_tmp = dataFile.readStringUntil('\n');

    // totalRewardNum
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.totalRewardNum = string_tmp.toInt();
    // reward_left
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.reward_left = string_tmp.toInt();
    // reward_right
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.reward_right = string_tmp.toInt();
    // reward_middle
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.reward_middle = string_tmp.toInt();

    // GaveFreeReward
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.GaveFreeReward.flag_L_water = string_tmp.toInt();
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.GaveFreeReward.flag_R_water = string_tmp.toInt();
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.GaveFreeReward.flag_M_water = string_tmp.toInt();
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.GaveFreeReward.past_trials = string_tmp.toInt();

    // TrialBlockInitPeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.TrialBlockInitPeriod = string_tmp.toInt();
    // SamplePeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.SamplePeriod = string_tmp.toInt();
    // DelayPeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.DelayPeriod = string_tmp.toInt();
    // TimeOut
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.TimeOut = string_tmp.toInt();
    // AnswerPeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.AnswerPeriod = string_tmp.toInt();
    // ConsumptionPeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.ConsumptionPeriod = string_tmp.toInt();
    // StopLickingPeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.StopLickingPeriod = string_tmp.toInt();
    // EarlyLickPeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.EarlyLickPeriod = string_tmp.toInt();
    // retention_counter
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.retention_counter = string_tmp.toInt();
    // low_light_intensity
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.low_light_intensity = string_tmp.toInt();
    // high_light_intensity
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.high_light_intensity = string_tmp.toInt();
    // extra_TimeOut
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.extra_TimeOut = string_tmp.toInt();
    // Trial_txt_position
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.Trial_txt_position = string_tmp.toInt();
    // Tevent_txt_position
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.Tevent_txt_position = string_tmp.toInt();
    // PreCueDelayPeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.PreCueDelayPeriod = string_tmp.toInt();
    // PreCuePeriod
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.PreCuePeriod = string_tmp.toInt();
    // hardestTrials
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.hardestTrials = string_tmp.toInt();
    // rule
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n');
    S.rule = string_tmp.toInt();
  }
  else
  {
    Serial.println("E: Error opening paraS.txt for read");
    dataFile.close();
    return -1;
  }
  dataFile.close();
  return 0;
}

// Write Fixation Events to SD card
int write_SD_event()
{
  File dataFile = SD.open("event.txt", FILE_WRITE);
  if (dataFile)
  {
    for (int i = 0; i < Ev.events_num; i++)
    {
      dataFile.print(Ev.events_time[i]);
      dataFile.print(" ");
      dataFile.print(Ev.events_id[i]);
      dataFile.print(" ");
      dataFile.println(Ev.events_value[i]);
    }
  }
  else
  {
    Serial.println("Error opening event.txt");
    dataFile.close();
    return -1;
  }
  dataFile.close();
  return 0;
}

int read_SD_cage_info()
{
  // read file to identify the cage number
  File dataFile = SD.open("cage_info.txt", FILE_READ);
  if (dataFile)
  {
    dataFile.seek(0);
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n'); // 1st line: cage_id = xx
    cage_id = string_tmp.toInt();
    string_tmp = dataFile.readStringUntil('=');
    string_tmp = dataFile.readStringUntil('\n'); // 4th line: task = xx
    string_tmp.toCharArray(task_name, 40);
  }
  else
  {
    Serial.println("Can not open file: 'cage_info.txt'.");
    dataFile.close();
    return -1;
  }
  dataFile.close();
  return 1;
}

int write_SD_cage_info()
{
  File dataFile = SD.open("cage_info.txt", FILE_WRITE_BEGIN);
  if (dataFile)
  {
    dataFile.print("cage_id = ");
    dataFile.println(cage_id);
  }
  else
  {
    Serial.println("Can not open file: 'cage_info.txt'.");
    dataFile.close();
    return -1;
  }
  dataFile.close();
  return 1;
}

// Write Trial info to SD card 
int write_SD_trial_info()
{
  File dataFile = SD.open("Trial.txt", FILE_WRITE);
  if (dataFile)
  {
    // time
    dataFile.print(Teensy3Clock.get());
    dataFile.print(" ");

    // trial#
    dataFile.print(S.currTrialNum);
    dataFile.print(" ");

    dataFile.print(S.currProtocolIndex);
    dataFile.print(" ");

    dataFile.print(TrialType); 
    dataFile.print(" ");

    dataFile.print(TrialOutcome);
    dataFile.print(" ");

    dataFile.print(S.SamplePeriod);
    dataFile.print(" ");

    dataFile.print(S.DelayPeriod);
    dataFile.print(" ");

    dataFile.print(is_earlylick);
    dataFile.print(" ");

    dataFile.print(S.rule); 
    dataFile.print(" ");

    dataFile.print(currStimu[0]);
    dataFile.print(" ");

    dataFile.print(currStimu[1]);
    dataFile.print(" ");

    dataFile.print(BaselineTrialFlag);
    dataFile.print(" ");

    // state_visited
    dataFile.print(trial_res.nVisited);

    for (int i = 0; i < trial_res.nVisited; i++)
    {
      dataFile.print(" ");
      dataFile.print(trial_res.stateVisited[i]);
      dataFile.print(" ");
      dataFile.print(trial_res.stateTimeStamps[i]);
    }

    dataFile.println();

  }
  else
  {
    Serial.println("E: error opening Trial.txt'.");
    dataFile.close();
    return -1;
  }
  dataFile.close();

  // Tevent.txt
  dataFile = SD.open("Tevent.txt", FILE_WRITE);
  if (dataFile)
  {
    dataFile.print(S.currTrialNum);
    dataFile.print(" ");

    dataFile.print(trial_res.nEvent);
    for (int i = 0; i < trial_res.nEvent; i++)
    {
      dataFile.print(" ");
      dataFile.print(trial_res.EventID[i]);
      dataFile.print(" ");
      dataFile.print(trial_res.eventTimeStamps[i]);
    }
    dataFile.println();
  }
  else
  {
    Serial.println("E: error opening Tevent.txt");
    dataFile.close();
    return -1;
  }
  dataFile.close();
  return 0;
}

void rule_define(int rule , float stimu1 ,float stimu2){
    if(rule == 0){ // attend to stimu1 location
        SampleType = 2; // easiest trial type
        if(stimu1 == -1){ // left
          TrialType = 1; 
        }
        else if(stimu1 == 1){ // right
          TrialType = 2; 
        }
    }
    else if(rule == 1){ // attend to stimu2 freq
        if(stimu2 < 0){
          TrialType = 1; // left
        }
        else if(stimu2 > 0){
          TrialType = 2; // right 
        }else{
          TrialType = int(random(1,3)); // random
        }
        
        SampleType = abs(stimu2) * 2;
    }
    else if(rule == 2){ // attend to stimu2 reversal freq
        if(stimu2 < 0){
           TrialType = 2; 
        }
        else if(stimu2 > 0){
          TrialType = 1;  
        }else{
          TrialType = int(random(1,3)); // random
        }

        SampleType = int(abs(stimu2) * 2);
    }
}


/***************************************Other functions************************************************/
int sum_array(byte a[], int array_length)
{
  int res = 0;
  for (int i = 0; i < array_length; i++)
  {
    res = res + a[i];
  }
  return res;
}


int compare_array_sum(byte array1[], byte oprant1, byte array2[], byte oprant2, int start_ind, int end_ind)
{
  int num = 0;
  for (int i = start_ind; i < end_ind; i++)
  {
    if (array1[i] == oprant1 && array2[i] == oprant2)
    {
      num++;
    }
  }
  return num;
}


int compare_array_sum(byte array1[], byte oprant1, int start_ind, int end_ind)
{
  int num = 0;
  for (int i = start_ind; i < end_ind; i++)
  {
    if (array1[i] == oprant1)
    {
      num++;
    }
  }
  return num;
}

void free_reward(int rew_duration_ms)
{
  smart.ManualOverride("DO1", 1); // override valve
  smart.ManualOverride("DO2", 1); // override valve
  smart.ManualOverride("DO3", 1); // override valve
  delay(rew_duration_ms);
  smart.ManualOverride("DO1", 0);
  smart.ManualOverride("DO2", 0);
  smart.ManualOverride("DO3", 0);
}

void system_output_check(){
  analogWriteFrequency(2,3000);
    analogWrite(2, 128);
    analogWrite(5,10);
    delay(200);
    analogWriteFrequency(2,10000);
    analogWrite(2, 128);
    delay(200);
    analogWrite(2, 0);
    analogWrite(5,0);
    delay(500);
    // middle
    analogWriteFrequency(3,3000);
    analogWrite(3, 128);
    analogWrite(9,10);
    delay(200);
    analogWriteFrequency(3,10000);
    analogWrite(3, 128);
    delay(200);
    analogWrite(3, 0);
    analogWrite(9,0);
    delay(500);
  
    // right
    analogWriteFrequency(16,3000);
    analogWrite(16, 128);
    analogWrite(20,10);
    delay(200);
    analogWriteFrequency(16,10000);
    analogWrite(16, 128);
    delay(200);
    analogWrite(16, 0);
    analogWrite(20,0);
    delay(500);
}

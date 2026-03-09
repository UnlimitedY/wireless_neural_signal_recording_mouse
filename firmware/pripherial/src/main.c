/*
 * include
 */
#include <zephyr/drivers/gpio.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>

#include "..\RHD_Recording\RHDRecording.h"
#include "..\ESB_wireless\ESB_wireless.h"

#include "..\Sensor_recording\LC709204F.h"
#include "..\Sensor_recording\LSM6DS3.h"
#include "..\Sensor_recording\mp2710.h"

// for debugging
#include <zephyr/logging/log.h>
#include <string.h>
// for DSP
#include "..\RHD_Recording\OnlineFilter.h"

#define LOG_MODULE_NAME LFP_Recording_peripherial
LOG_MODULE_REGISTER(LOG_MODULE_NAME);
/*
 * typedef
 */
typedef unsigned char u8_t;
typedef unsigned short u16_t;
typedef unsigned int u32_t;

/*
* Recording channels number
* mode0 : 16 channels lfp 1Khz recording
* mode1 : 16 channel spike 20Khz recording; single raw data + 16 MUA
* mode2 : 4 channel 20Khz raw data;
* mode3 : 16 channel ESA recording; 1Khz (downsampling from 12.5Khz) + MUA
*/
#define Channel_recorded 16
#define Channel_recorded_spike 16 // selected channel indices <= Channel_recorded
u8_t raw_channel[Channel_recorded_spike] = {0, 1, 2, 3, 4, 5, 6, 7 ,8 ,9 ,10 ,11 ,12 ,13 ,14 ,15}; 
u8_t recorded_channel_num = Channel_recorded_spike; // default: enable all channels

// nrf_gpio_pin_control_select
/*
 * extern marco define and struct define
 */
u16_t init_tx_buf[1];
u16_t init_rx_buf[1];

/***********************mode0********************* */
// for LFP 16 channels raw data
u16_t m_tx_buf[LFP_TX_BUFFER_SIZE];
u16_t m_rx_buf[2][LFP_RX_BUFFER_SIZE];

u16_t channel_array_t[SAMPLE_POINT_NUM * time_window];
u16_t channel_array[Channel_recorded][SAMPLE_POINT_NUM * time_window];
#define MODE0_DECIMATED_SAMPLES_PER_CHANNEL ((SAMPLE_POINT_NUM * TARGET_FS) / ORIGINAL_FS)
float32_t mode_0_input_buffer[Channel_recorded * SAMPLE_POINT_NUM * time_window];
float32_t mode_0_decimated_buffer[Channel_recorded * MODE0_DECIMATED_SAMPLES_PER_CHANNEL];
u16_t mode_0_array_lfp_t[Channel_recorded * MODE0_DECIMATED_SAMPLES_PER_CHANNEL];

/***********************mode3********************* */
u16_t mode_3_m_tx_buf[MODE_3_TX_BUFFER_SIZE]; // ppi convert command; /**< TX buffer. */
u16_t mode_3_m_rx_buf[2][MODE_3_RX_BUFFER_SIZE]; /*< RX buffer. double buffer >*/

u16_t mode_3_array_t[MODE_3_SPI_RX_BUF_SIZE];
u16_t mode_3_array_lfp_t[MODE_3_LFP_SIZE];
u16_t mode_3_array_esa_t[MODE_3_ESA_SIZE];
// mode3 原始数据缓冲计数与设定：累计4个chunk后合并一次性发送
#define MODE3_RAW_BUFFER_CHUNKS 4
u8_t mode3_raw_chunk_count = 0; // 当前已缓冲的chunk数量（0~4）
u16_t mode_3_array_t_raw[Channel_recorded][CHUNK_SIZE * MODE3_RAW_BUFFER_CHUNKS]; // 做一个缓冲来最大话利用esb包的空间；
/***********************mode1, 2 spike********************* */
u16_t spike_m_tx_buf[SPIKE_TX_BUFFER_SIZE]; 
u16_t spike_m_rx_buf[2][SPIKE_RX_BUFFER_SIZE]; 

u16_t spike_channel_array_t[SPIKE_SAMPLE_POINT_NUM * time_window];
u16_t spike_channel_array[Channel_recorded_spike][SPIKE_SAMPLE_POINT_NUM * time_window];	

u16_t MutiUnitActivityArray[(SPIKE_SAMPLE_POINT_NUM / MUA_BIN_SIZE) * time_window]; 

// spi instance init
const nrfx_spim_t spi = NRFX_SPIM_INSTANCE(SPI_INSTANCE);
const nrfx_spim_t spi_init = NRFX_SPIM_INSTANCE(SPI_INSTANCE_INIT); // for imu and rhd init

volatile uint32_t spi_overflow_flag = 0;

u16_t RHD_command = 0x00ff;

const u16_t NINE_DUMMPY[9] = {0x00ff, 0x00ff, 0x00ff, 0x00ff, 0x00ff, 0x00ff, 0x00ff, 0x00ff, 0x00ff};

// low power
const u16_t Register_config_lowpower[18] = {Register0_disable, lfp_Register1, lfp_Register2, lfp_Register3, lfp_Register4, 
                                        lfp_Register5, lfp_Register6, lfp_Register7, lfp_Register8, lfp_Register9, lfp_Register10, 
                                        lfp_Register11, lfp_Register12, lfp_Register13, lfp_Register14, lfp_Register15, 
                                        lfp_Register16, lfp_Register17};
/////////////////////////////////////// 1Khz sampling rate                                       
// mode 0
const u16_t Register_config_lfp[18] = {lfp_Register0_enable, lfp_Register1, lfp_Register2, lfp_Register3, lfp_Register4, 
                                        lfp_Register5, lfp_Register6, lfp_Register7, lfp_Register8, lfp_Register9, lfp_Register10, 
                                        lfp_Register11, lfp_Register12, lfp_Register13, lfp_Register14, lfp_Register15, 
                                        lfp_Register16, lfp_Register17};

/////////////////////////////////////// 20Khz sampling rate  
// mode 1
const u16_t Register_config_spike[18] = {spike_Register0_enable, spike_Register1, spike_Register2, spike_Register3, spike_Register4, 
                                        spike_Register5, spike_Register6, spike_Register7, spike_Register8, spike_Register9, 
                                        spike_Register10, spike_Register11, spike_Register12, spike_Register13, spike_Register14, 
                                        spike_Register15, spike_Register16, spike_Register17};
// mode 2
const u16_t Register_config_spike_raw[18] = {spike_Register0_enable, spike_Register1, spike_Register2, spike_Register3, 
        spike_raw_Register4, 
                                        spike_Register5, spike_Register6, spike_Register7, spike_Register8, spike_Register9, 
                                        spike_Register10, spike_Register11, spike_Register12, spike_Register13, spike_Register14, 
                                        spike_Register15, spike_Register16, spike_Register17};

/////////////////////////////////////// 12.5Khz sampling rate  
// mode 3
const u16_t Register_config_mode3[18] = {spike_Register0_enable, 
        spike_mode3_Register1, spike_mode3_Register2, spike_Register3, spike_mode3_Register4, 
                                        spike_Register5, spike_Register6, spike_Register7, spike_Register8, spike_Register9, 
                                        spike_Register10, spike_Register11, spike_Register12, spike_Register13, spike_Register14, 
                                        spike_Register15, spike_Register16, spike_Register17};

const nrfx_gpiote_t gpiote_instance = NRFX_GPIOTE_INSTANCE(GPIOE_INST); 

const nrfx_timer_t RHD_timer_nRFX = NRFX_TIMER_INSTANCE(1);
const nrfx_timer_t SPI_timer_RESET = NRFX_TIMER_INSTANCE(3);

/********************************Sample rate**********************************/
bool mode_switch_flag = false; 
u8_t mode3_esa_reref_enable = MODE3_ESA_REREF_FAST_MEDIAN; // default using switch network

u16_t sampe_mode = 0; // default mode0
uint32_t timer_period = 50; // default value 
uint32_t reset_ticks_value = SPI_RX_BUF_SIZE;

volatile bool spi_buff_flag = false;
volatile bool buffer_is_full = false;

uint8_t gp_channel_1;
uint8_t gp_channel_2;
uint8_t gp_channel_3;

uint8_t gpiote_channel;
/*
 * hypo function
 */
#define reversebit(x, y) x ^= (1 << y)

u16_t tx_payload_wraped_num = 0; // count the number of wrapped tx packages
/***********************for debugging and cue************************/ 
#define LED0_NODE DT_ALIAS(led0) // macro function of devicetree; test led

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(LED0_NODE, gpios);

void LED_hinting(uint32_t interval, uint32_t eventNum){
        // interval: 2000; 1000; 500; 200 
        u16_t events = 0;
        while(1)
        { 
                gpio_pin_toggle_dt(&led);
                k_sleep(K_MSEC(interval));
                events++;
                if(events >= 2*eventNum){
                        break;
                }
        }
}

/***********************for low-power setting************************/ 
k_tid_t mainThread;
// 记录 每一次 发送 数据包 允许休眠的时间
static u32_t timerecording; // 

/**************************system flag & command_flag & spike detection params**************************************/
// system flags
int RHD_err, err;

bool sample_switch = false; // 初始化程序的时候默认直接进入到采样lfp数据sample 的阶段

// esb package head & control flags
u32_t packet_timestamp = 0; 
uint32_t timestamp_HABITS = 0;
uint32_t timestamp_baseline = 0;
uint32_t timestamp_LTNSRS = 0;

uint32_t packet_sent_counter[2] = {0, 0}; // success ; fail ; flag

bool overflow_signal = 0;
bool sensor_update_flag = 0;
uint64_t stamp_check = 0;

// fixed for mode 2
static u8_t data_size_per_channel_packets = 30; // SPIKE_SAMPLE_POINT_NUM / 3packets == 90 / 3 == 30
u16_t temp_spike_channel_array[120]; // data_size_per_channel_packets * 4 channels == 120
u8_t spike_raw_channel[4] = {0, 1, 2, 3}; // mode 2

// selectable for mode 1
u8_t recorded_spike_channel = 0; // default: enable channel 0; mode 1

// neural recording for mode 0
u8_t channel_order[Channel_recorded] = {14, 15, 0, 1, 2, 3, 4, 5, 6, 7 ,8 ,9 ,10 ,11 ,12 ,13}; 
u8_t channel_order_spike[Channel_recorded_spike] = {14, 15, 0, 1, 2, 3, 4, 5, 6, 7 ,8 ,9 ,10 ,11 ,12 ,13}; 
/********************************sensor setup**********************************/
const nrfx_twim_t lc_twim = NRFX_TWIM_INSTANCE(LC_INSTANCE_ID);
const nrfx_spim_t lsm_spi = NRFX_SPIM_INSTANCE(LSM_INSTANCE_ID);
uint8_t twimWriteDataBuffer[TWI_MAX_NUM_TX_BYTES];
uint8_t LCDataBuffer[6];

/************************** ESB defination **************************************/
uint8_t bitrate = 1; // 1 : 1mbps; 2: 2mbps
uint8_t rf_channel = 5; // index of rf_ channel
uint8_t advise_channel = 0;
uint8_t rf_channel_list[rf_channel_num] = {2, 17, 33, 50, 67, 84}; // aviod conflict with WiFi
uint8_t rf_channel_rssi_list[rf_channel_num] = {0};

struct esb_payload rx_payload; // command & behavioral events --rx
struct esb_payload tx_payload; // neural signal -- tx

struct esb_payload empty_payload; // when sampling disable 
struct esb_payload timestamp_payload; // neural signal alignment required

u32_t last_statistic_timestamp;
uint8_t sample_watch_dog = 0;

/***********************************TWI Setup function******************************************/
/*
* 通过IMU来读取一定sample rate的3轴数据，在单次包的发送中，将该数据放入并一起发送到上位机；
*/
int16_t imu_data[6];
int16_t lc_data[3];

struct IMU_settings settings;

// EN_HIZ; CEB; shipping
u8_t IMU_init[2] = {0, 0}; //mode index: low-power; ACCEL; ACCEL + GYRO;    update_flag

void IMU_mode_switch(void){
        if(sampe_mode != 2){ // sample mode 2 will not record IMU data
                if(IMU_init[0] == 1){
                settings.accel_enable = 0;
                settings.gyro_enable = 0;
                }
                else if(IMU_init[0] == 2){
                settings.accel_enable = 1;
                settings.gyro_enable = 0;
                }
                else if(IMU_init[0] == 3){
                settings.accel_enable = 1;
                settings.gyro_enable = 1;
                }
                else{
                // default
                settings.accel_enable = 0;
                settings.gyro_enable = 0;
                }
        }else{
                settings.accel_enable = 0;
                settings.gyro_enable = 0; 
        }

        err = LSM6DS3_init();
}

void setup_sensor(void){ // 注意，nrf 通过内部上拉来驱动 lsm 会导致 发热问题，可能是gpio 上拉电流过大
	int err;
        // init lsm spim
        err= lsm_spim_init();
        k_sleep(K_MSEC(500));
        LOG_INF("lsmspi init %d \n" ,err);
	// 初始化 LSM
	err = LSM6DS3_who_am_i();
	if(err != -1){
		LOG_INF("LSM init failed\n");
		while(1) {
                err = LSM6DS3_who_am_i();
                if(err == -1){
                        break;
                }
                LOG_INF("%d \n" ,err);
                LED_hinting(200, 2);
                k_sleep(K_SECONDS(1));
                }
	}
        LOG_INF("LSM init success\n");
        settings.accel_enable = 0;
        settings.gyro_enable = 0; 
	err = LSM6DS3_init(); // 初始化为 低功耗模式，全部关闭
        /******* for LC *******/
        twim_init(); 
        k_sleep(K_MSEC(500)); // 注意，设备的初始化需要一定的时间
        // 初始化 LC battery
	int LCID; // APT
	LCID = getChipID();
	while(LCID != 0x001e){
                LED_hinting(500, 2);
                LOG_INF("LC battery init failed %x \n" ,LCID);
                LCID = getChipID();
                k_sleep(K_SECONDS(1));  
	}
	// 50mAH capacity ;
	LC_init();
        // charge indiciator init
        Charging_stats_init();
}

void LSM6DS3_Read(void){ // only recording 3-axis
        /*
        * 记录 6-axis的值；关闭 角加速度测量；注意：在lsm_init中要对应开启角加速度mode和配置寄存器
        */
       if(IMU_init[0] == 2){
                LSM6DS3_read_accl_data();
       }
        else if(IMU_init[0] == 3){
                LSM6DS3_read_accl_data();
                LSM6DS3_read_gyro_data();
        }
}

void BatteryPower_Temp_Read(u16_t *data){ // not used
	// RSOC
	LC_getRSOC(data); // 0-100%
	// charging_stat
	Charging_PG_PG_STAT_get(data + 1);
        // battery_voltage
        LC_getCellVoltage(data + 2);
}

/************************** main-used function **************************************/
int filter_init(float threshold_default){
        arm_status status;
        //////////////////////// For LFP 2 order IIR low pass filter Fc = 250Hz
        status = init_lowpass_filter_LFP(IIR_ORDER_lowpass_LFP, IIR_CUTOFF_lowpass_LFP, ORIGINAL_FS);
        if (status != ARM_MATH_SUCCESS) {
                LOG_INF("Error: LFP low-pass filter initialization failed\n");
                return -1;
        }
        
        //////////////////////// For ESA
         // Initialize 1th order low-pass filter at 12Hz
        status = init_lowpass_filter_ESA(IIR_ORDER_lowpass_ESA, IIR_CUTOFF_lowpass_ESA, ORIGINAL_FS);
        if (status != ARM_MATH_SUCCESS) {
                LOG_INF("Error: ESA Low-pass filter initialization failed\n");
                return -1;
        }
        
        // Initialize 4th order high-pass filter at 300Hz
        status = init_highpass_filter_ESA(IIR_ORDER_highpass_ESA, IIR_CUTOFF_highpass_ESA, ORIGINAL_FS);
        if (status != ARM_MATH_SUCCESS) {
                LOG_INF("Error: ESA High-pass filter initialization failed\n");
                return -1;
        }

        // Set spike detection thresholds
        for (int ch = 0; ch < NUM_CHANNELS; ch++) { 
                set_spike_threshold(ch, threshold_default); // Varying thresholds, default; -100uV
        }
        LOG_INF("Filter initialization completed successfully\n");
        return 0;
}

u16_t init_everything(void){
        /*************LED setup***************/
	if (!gpio_is_ready_dt(&led)) {
                LOG_INF("failed");
		return 0;
	}
	err = gpio_pin_configure_dt(&led, GPIO_OUTPUT_ACTIVE);
	if (err < 0) {
		return 0;
	}

        // // /****************spi_transmit & spi_init init******************/     
        err = spim_init();
        if(err != 0){
                LOG_INF("fail SPI init %d" , err);
                LOG_INF("%d" , spi.p_reg->FREQUENCY);
                return 0;
        }

        /**************** lsm & lc: twi init ******************/ 
        memset(imu_data, 0, sizeof(imu_data));
        memset(lc_data, 0, sizeof(lc_data));
        
        setup_sensor(); // only accel; 104Hz
        /**************** ESB init ******************/     
        err = clocks_start();
	if (err)
	{
                LOG_INF("fail ESB clock init %d" , err);
		return 0;
	}
        err = esb_initialize();
	if (err)
	{
                LOG_INF("fail ESB init %d" , err);
		return 0;
	}

        empty_payload.length = 10;
        timestamp_payload.length = 12;

        tx_payload.pipe = 0; // using the pipe 0
        empty_payload.pipe = 0;
        timestamp_payload.pipe = 0;

        esb_flush_tx(); 
	esb_flush_rx();
}

u16_t init_RHD(){
        rhdspi_init();
        if(sampe_mode == 0){// 1Khz 16 channels
                // timer_period: 1000 / sample rate (KHz) / Channel_num 
                // esb_set_tx_power(ESB_TX_POWER_0DBM); 
                timer_period = 5;
                reset_ticks_value = SPI_RX_BUF_SIZE;
                RHD_err = RHD_init(Register_config_lfp);
                
        }else if(sampe_mode == 1){ // 20Khz 16 channels: xx ms per packets
                // esb_set_tx_power(ESB_TX_POWER_4DBM); 
                timer_period = 1000 / 20 / Channel_recorded_spike; // 5: 12500 Hz ; 6: 10417 Hz ;  3: 20833 Hz; 4: 15625 Hz (0 dummy)
                reset_ticks_value = SPIKE_SPI_RX_BUF_SIZE;
                RHD_err = RHD_init(Register_config_spike);
        }else if(sampe_mode == 2){ 
                // spike 20khz 4 channels
                // esb_set_tx_power(ESB_TX_POWER_4DBM); 
                timer_period = 1000 / 20 / Channel_recorded_spike;
                reset_ticks_value = SPIKE_SPI_RX_BUF_SIZE;
                RHD_err = RHD_init(Register_config_spike_raw);
        }else if(sampe_mode == 3){
                // esb_set_tx_power(ESB_TX_POWER_4DBM); 
                // spike 12.5khz + 1khz lfp
                timer_period = 5;  // 1000 / 12.5 / Channel_recorded
                reset_ticks_value = MODE_3_SPI_RX_BUF_SIZE;
                RHD_err = RHD_init(Register_config_mode3);
        }
        /****************RHD init******************/ // using cs gpiote task
        if (RHD_err)
        {
                LOG_INF("failed RHD init %x" , RHD_err);
                while(1){k_sleep(K_SECONDS(1000));};
                return 0;
        }else{
                LOG_INF("RHD init success");
        }

        nrfx_spim_uninit(&spi_init); // for low-power

        /****************PPI nerual recording init******************/
        err = timer_init(timer_period, reset_ticks_value);
        if(err != 0){
                LOG_INF("failed timer init %d" , err);
                while(1){k_sleep(K_SECONDS(1000));};
		return 0; 
        }
        err = CS_Gpiote_init();// 注意，之后无法再直接使用cs来做spi传输
        if(err != 0){
                LOG_INF("failed gpiote init %d" , err);
                while(1){k_sleep(K_SECONDS(1000));};
		return 0; 
        }
        err = ppi_init();
        if(err != 0){
                LOG_INF("failed ppi init %d" , err);
                while(1){k_sleep(K_SECONDS(1000));};
		return 0; 
        }

        LOG_INF("success all init");
}

u16_t low_power(void){
        // RHD
        nrfx_gpiote_out_task_disable(&gpiote_instance, NRFX_SPIM_SS_PIN); // 避免两个spi的冲突
        rhdspi_init();
        RHD_err = RHD_init(Register_config_lowpower);
        nrfx_spim_uninit(&spi_init); // for low-power
        nrfx_gppi_channels_disable(BIT(gp_channel_1));
	nrfx_gppi_channels_disable(BIT(gp_channel_2));
        // LSM
        settings.accel_enable = 0;
        settings.gyro_enable = 0; 
        err = LSM6DS3_init();
}


void structure_rx_data(){
        // deal with overflow
        if(spi_overflow_flag){
                if(sampe_mode == 0){ // lfp
                        for(int j=0 ; j<spi_overflow_flag ; j++){
                                m_rx_buf[spi_buff_flag][j] = m_rx_buf[!spi_buff_flag][SPI_TX_BUF_SIZE + j];
                        } 
                }else if(sampe_mode < 3){ // spike 20Khz
                        for(int j=0 ; j<spi_overflow_flag ; j++){
                                spike_m_rx_buf[spi_buff_flag][j] = spike_m_rx_buf[!spi_buff_flag][SPIKE_SPI_TX_BUF_SIZE + j];
                        } 
                }else{ // raster 12.5khz + lfp：
                        for(int j=0 ; j<spi_overflow_flag ; j++){
                                mode_3_m_rx_buf[spi_buff_flag][j] = mode_3_m_rx_buf[!spi_buff_flag][MODE_3_SPI_TX_BUF_SIZE + j];
                        } 
                }
        }

        // proprocess raw data
        if(sampe_mode == 0){ // 16 LFP raw data
                for (u16_t g = 0; g < sizeof(channel_array[0]) / 2; g++) // loop 7 times
                {       // 100 sample points each channel
                        for (u16_t u = 0; u < CONVERT_FASHION_NUM; u++)
                        {
                                // 2 steps delay converted result
                                if (channel_order[u] < Channel_recorded)
                                {       
                                        channel_array[channel_order[u]][g] = m_rx_buf[!spi_buff_flag][CONVERT_FASHION_NUM * g + u];
                                }
                        }
                } // channel_array shape is 16 * 100 u16_t ; 
        }else if(sampe_mode < 3){ //  spike raw data + MUA : 20Khz
                for (u16_t g = 0; g < sizeof(spike_channel_array[0]) / 2; g++) // loop 90 times
                {       // 90 sample points each channel
                        for (u16_t u = 0; u < SPIKE_CONVERT_FASHION_NUM; u++)
                        {
                                // 2 steps delay converted result
                                if (channel_order_spike[u] < Channel_recorded_spike)
                                {       
                                        spike_channel_array[channel_order_spike[u]][g] = spike_m_rx_buf[!spi_buff_flag][SPIKE_CONVERT_FASHION_NUM * g + u];
                                }
                        }
                } // channel_array shape is 16 * 100 u16_t ; 
        }else{ // raster + lfp 12.5khz
                for (u16_t P_size = 0; P_size < CHUNK_SIZE; P_size++) // loop 48 times
                {       // 30 sample points each channel
                        for (u16_t ch = 0; ch < NUM_CHANNELS; ch++)
                        {
                                // 2 steps delay converted result
                                if (channel_order[ch] < Channel_recorded)
                                {       
                                        mode_3_array_t[ch * CHUNK_SIZE + P_size] = mode_3_m_rx_buf[!spi_buff_flag][NUM_CHANNELS * P_size + ch];
                                }
                        }
                }
                convert_rhd2132_samples(mode_3_array_t, input_buffer, MODE_3_SPI_RX_BUF_SIZE, Filter_scale, 1);
        }
}

/*   Mode 1
* spike detection algorithm--- v0.1 only consider the noise level and get the threshold from it
* 整体的思路是: 首先将所有的sample 值大于threshold的得到index值，之后通过记录上升沿的spike来作为spike 的timestamp
* 之后去掉ISI 小于2ms的spike 和在这一段数据中边缘的过短的spike；最终得到spike 的timestamp
* L: 21 -> 21 points each spike (overlap half length in 20khz sampling) (per spike lasting 2 ms)
* ****************************************************************
注意，进行spike detection就必须要进行lfp的去除，通过rhd的dsp去除lfp导致采集到的原始信号是没有lfp的
注意，threshold 范围为 0 ~ 32768；为绝对值
*/
int L = MUA_BIN_SIZE;
int temp_ISI = SPIKE_SAMPLE_POINT_NUM * time_window + 1;
int first_spike_index = 0;
int last_spike_index = 0;
int spike_num_per_bin = 0;
u8_t channel_idx[SPIKE_SAMPLE_POINT_NUM * time_window + 1] = {0};
u8_t diff[SPIKE_SAMPLE_POINT_NUM * time_window] = {0};
u16_t threshold_temp = 0x0000;
u16_t temp_raw_data = 0;
u8_t PN_Flag[SPIKE_SAMPLE_POINT_NUM * time_window] = {0}; // 1 is positive ;0 is negative


// 这个list 用来保存当前所使用的各个通道的threshold，之后实时上传到GUI来进行显示 mode1
u16_t threshold_list[16] = {1000, 1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000 ,1000};

void get_MUA_data(u16_t channel_num)
{
        // re-init parameters
	first_spike_index = 0;
	last_spike_index = 0;
	spike_num_per_bin = 0;
	temp_ISI = SPIKE_SAMPLE_POINT_NUM * time_window + 1; 

	for (int j = 0; j < SPIKE_SAMPLE_POINT_NUM * time_window; j++)
	{
		temp_raw_data = (u16_t)(swapShort16(spike_channel_array[channel_num][j]));
                /* get absolute value */
		if (temp_raw_data < 0x8000) // unsigned encoding
		{       // negative value
			temp_raw_data = 0x8000 - temp_raw_data;
			PN_Flag[j] = 0;
		}
		else
		{       // positve value
			temp_raw_data = temp_raw_data - 0x8000;
			PN_Flag[j] = 1;
		}
                /* recording abs spike raw data of one channel */
		spike_channel_array_t[j] = temp_raw_data;
		// init the channel_idx and diff
		diff[j] = 0;
		channel_idx[j] = 0;
	}
        channel_idx[0] = 1; // defaultly drop the first data point.

	/* spike detection */
	threshold_temp = threshold_list[channel_num];
	for (int i = 1; i < sizeof(channel_idx); i++)
	{
		// 注意： 这里可以选择是使用positive value 来进行判断 spike 还是使用negative value；默认使用negative value	 
		if (spike_channel_array_t[i - 1] > threshold_temp && PN_Flag[i - 1] == 0)
		{
			channel_idx[i] = 1;
                        // 记录上升沿的spike来作为spike 的timestamp
			if (channel_idx[i - 1] == 0)
			{
				diff[i - 1] = 1;
			}
		}
	}
        /* remove bad spikes */
	// 1. delete spikes ISI < 1ms 21 sample points in 20kHz sampling
	for (int j = 0; j < sizeof(diff); j++)
	{
		if (diff[j] == 1)
		{
			if (temp_ISI == SPIKE_SAMPLE_POINT_NUM * time_window + 1) // the first value
			{
				temp_ISI = j;
				first_spike_index = j;
			}
			else
			{
				if (j - temp_ISI < L)
				{       // 这一步保证两个spike 之间至少差L个sample points, 去掉相对延迟的 spike
					diff[j] = 0;
				}
				else
				{
					temp_ISI = j;
				}
			}
		}
	}
	last_spike_index = temp_ISI;

	// 2. delete spikes on edges (the first and the last one) shorter than L
                // last one
        if (last_spike_index != SPIKE_SAMPLE_POINT_NUM*time_window + 1){ // ensure there has spike detected
                 // end edge
                if (last_spike_index + L >= SPIKE_SAMPLE_POINT_NUM*time_window)
                {
                        diff[last_spike_index] = 0;
                }
        
                // first one
                if ((first_spike_index - L) <= 0) // onset edge
                {
                        diff[first_spike_index] = 0;
                }
        }
	
        /* compress the MUA data to 1 bit/sample */
	        // 对MutiUnitActivityArray进行操作，注意对每一个元素都要操作以免数据的残余影响
	int k = 0;
	for (int i = 0; i < sizeof(diff); i += L)
	{      
		spike_num_per_bin = 0;
		for (int j = 0; j < L; j++)
		{
			spike_num_per_bin += diff[i + j];
		}
		if (spike_num_per_bin >= 1)
		{
			MutiUnitActivityArray[k] = (1 << channel_num) | MutiUnitActivityArray[k]; // set 1 to given channel bit ; lowest bit is channel 0; MSB is channel 15
		}
		else
		{
			MutiUnitActivityArray[k] = ~(1 << channel_num) & MutiUnitActivityArray[k]; // set 0
		}
                k++;
	}
}

/**
 * Other Functions
 * 
 */
void running_time_offset(uint8_t test){
        LOG_INF("%u us running time! %d test \n", k_cyc_to_us_floor32(k_cycle_get_32()) - timerecording, test);
}
void running_time_onset(void){
        timerecording = k_cyc_to_us_floor32(k_cycle_get_32());
}

int dynamic_retransmit(void){
        /* 
        * 动态改变重发次数：(根据发送 （失败)/(失败 + 成功) 的比率)
        * 1. 0% - 50%：2
        * 2. 50% -100%： 3
        * Special case: 100% : 0; lasting n : 暂停 sample
        */ 
       // 确认是否处于esb idle 状态
        if(!esb_is_idle()){
                return -1;
        }

        if((packet_timestamp - last_statistic_timestamp > 1000)){ // about 50 packets
                if((packet_sent_counter[0] + packet_sent_counter[1] == 0)){
                        last_statistic_timestamp = packet_timestamp;
                        return -2;
                }

                // 获得 发送接收指标： 发送失败率
                u32_t indicate_commu = (packet_sent_counter[1] * 100) / ((packet_sent_counter[1] + packet_sent_counter[0])); // 百分位
                // change retransmit count
                if(indicate_commu < 1){
                        sample_watch_dog = 0;
                        esb_set_tx_power(ESB_TX_POWER_0DBM); 
                        // esb_set_retransmit_count(1); // 2
                }else if(indicate_commu <= 100){
                        sample_watch_dog++;
                        esb_set_tx_power(ESB_TX_POWER_4DBM); 
                        // esb_set_retransmit_count(1); // 3
                }
                
                // // 确定是否 需要暂停
                // if(sample_watch_dog > 100){ // 100s
                //         esb_set_retransmit_count(1);
                //         sample_switch = false;
                //         sample_watch_dog = 0;
                // }      

                // 每过 500ms 重新统计 信号记录指标
                last_statistic_timestamp = packet_timestamp;
                packet_sent_counter[0] = 0;
                packet_sent_counter[1] = 0;
        
        }
        return 0;
}

/****************************main**************************************/
int main(void)
{       /* power consumption */
        /* 1. 1.7mA 所有都没哟
        * 2. + init_everything: 2.2 mA (3.2mA max)
        * 3. + init_RHD(): 2.8 mA
        * 4. + led keep light: 2.95 mA
        * 5. + RHD samplerate: 1Khz 19 3.1 mA (16 channel)
        * 6. + no ksleep with empty loop: 8.5mA (+ 5.4mA)
        * 6. + sleep 0.5ms in while main loop without esb: 3.5mA
        * 7. sleep 0.1ms with esb: 8 mA
        * 8. + thread: 3.8mA ;2khz 16 channel 
        * 9. + IMU (104 Hz) 6-axis: ~4.5mA
        * 10. + spike 17khz: 38mW: 9.6mA 
        * 11. spike 17khz 4 channels raw data : 22mA -> 75mW
        */
        // static u32_t runingtime;

        /**************** main thread ******************/
        mainThread = k_sched_current_thread_query();
        u32_t packets_counter = k_uptime_get_32(); // 8192 ticks per sec 
        last_statistic_timestamp = packets_counter;

        /*
        ******************************************* setup ***********************************
        */
        bool sampling = false;
        init_everything();
        // TODO debug: 这里必须先初始化一次并开启10us的采样，不然就会导致第一次开始采样得到的数据是全0；
        init_RHD();
        timer_start();
        k_sleep(K_USEC(10));
        timer_stop(); 
        low_power();
        
        /****************************recording start******************************/
        /*********************main loop*********************/
	while (1) {
                /**********system command process**********/
                if(!sample_switch){
                        /* stop sampling */
                        if(sampling){
                             timer_stop();   
                             low_power();
                             sampling = false;
                        }
                        /* sample mode switch */
                        if(mode_switch_flag){
                                sample_switch = true;
                                continue;
                        }

                        BatteryPower_Temp_Read(lc_data);
                        /* empty esb packets */
                        err = empty_payload_wrap(lc_data);
                        if(err){
                                esb_flush_tx();
                                LOG_INF("%d esb empty payload failed", err);
                        }
                        LED_hinting(100, 2);

                }else if(!sampling){
                        /* re-configration rhd with specific sample mode */
                        // uninit gpiote re-init rhd
	                nrfx_gpiote_out_task_disable(&gpiote_instance, NRFX_SPIM_SS_PIN);
                        init_RHD();
                        nrfx_gpiote_out_task_enable(&gpiote_instance, NRFX_SPIM_SS_PIN);
                        nrfx_gpiote_out_set(&gpiote_instance, NRFX_SPIM_SS_PIN); // reset the CS line to disable
                        /* filter */
                        filter_init(50.f); // 这里设定的是uV值，在实际的设置中会自动根据 filter的放缩进行放缩
                        /* IMU init */
                        IMU_mode_switch();
                        
                        /* begining sample */
                        buffer_is_full = false;
                        sampling = true;
                        overflow_signal = !overflow_signal;
                        RHD_tx_buf_setup();
                        
                        // timestamp alignment
                        if(!mode_switch_flag){ // normal 
                                while(!esb_is_idle()){};
                                packet_sent_counter[1] = 0; // clear the esb fail flag
                                // rf_channel = 5; 
                                // 保证 在下位机到中继端的时间延迟最小
                                k_sleep(K_MSEC(1000));
                                esb_flush_tx();
                                esb_set_retransmit_count(0);
                                err = timestamp_payload_wrap();
                                while(!esb_is_idle()){};
                                // check if the command has sent success 这里如果上位机断开，将会无线循环下去
                                while(packet_sent_counter[1]){ // pop the newest packets
                                        // failed 
                                        packet_sent_counter[1] = 0;
                                        esb_flush_tx();
                                        // use next adv channel
                                        advise_channel++;
                                        if(advise_channel >= sizeof(rf_channel_list)){
                                                advise_channel = 0;
                                        }
                                        // esb_set_rf_channel(rf_channel_list[advise_channel]);
                                        err = timestamp_payload_wrap();
                                        while(!esb_is_idle()){};
                                }
                                // select the esb params
                                if(sampe_mode){
                                        esb_set_retransmit_count(3);  
                                }else{
                                        esb_set_retransmit_count(2);  // 2 比较稳定
                                }
                                esb_set_rf_channel(84);

                        }else{ // fast mode switch
                                mode_switch_flag = false;
                        }
                        
                        // start sampling
                        timer_start();
                        k_sleep(K_FOREVER);
                }

                /**********recording package processing**********/
                /* 
                * 注意：这里的最坏情况和txfifo的大小有关；为了避免SPI_RESET(2 priority)和ESB中断(0/1 priority)之间的冲突；
                * esb整个fifo使用最多的retransimit进行发送和rx回调函数处理的时间需要小于采样得到一个包的数据的所需时间
                * 一般情况esb所需时间：2[retransmit_count] * 8[txfifo_count] * 450[retransmit_delay] = 7.2 ms > 6.1 ms
                * 单个包的数据处理时间：< 1ms TODO
                * 通过设置上述三个参数esb可以为：1 * 4 * 450 = 1.8 ms 注意：fifo 还是要设置的大一些 4；重传次数的多少感觉并不能让传输
                * 变的稳定，还是需要大的fifo来让传输时间分散开了，更有利于稳定的传输；同时这样可以同时放多个包进去来增加速率
                * 现在使用 溢出检测的方法可以不需要要求esb 的传输必须在一个时间周期之内完成
                */

               /*
               注意： 目前在esb 驱动中，设置fifo 为 8,保证 三个模式的使用；同时重发失败后会丢弃，并进入esb 休眠 （esb 驱动改写）
               避免esb 的休眠周期被打乱导致功耗上升
               */
                if(buffer_is_full && sampling){ // a package is ready! 6.1ms per package for 96 data points
                /*** 0. next package process ***/
                        buffer_is_full = false;
                        tx_payload_wraped_num++;
                        // the timestamp is absolutely value from power up for each packages
                        packet_timestamp = k_uptime_get_32(); // ms CONFIG_SYS_CLOCK_TICKS_PER_SEC depend the time resolution
                        timestamp_LTNSRS = packet_timestamp;

                        dynamic_retransmit();
                        
                /*** 0.1. imu lc data read ***/
                        // 注意： memset 效率不高这个memset 函数
                        if(packet_timestamp - packets_counter >= 10){ // ~ 100Hz imu 
                                sensor_update_flag = 1;
                                packets_counter = packet_timestamp;
                                LSM6DS3_Read(); // 500us 6-axis blocking mode
                                BatteryPower_Temp_Read(lc_data);
                        }

                /*** 1. structured copy rx_buf data ***/
                        structure_rx_data(); // get channel_array cost 31us in nrf-52840 with u16_t data[16][6]
                        
                /*** 2. spike detection : MUA data ***/
                        if(sampe_mode == 1){ // cost 1648 us : 1.6ms in 17khz 16 channels
                                for (u16_t mua = 0; mua < Channel_recorded_spike; mua++)
				{	
                                        get_MUA_data(mua);
                                }
                        }
                /*** 2.1 online filtering mode 3  ***/
                        if(sampe_mode == 3){
                                // single channel Raw data recording（原始行为：每个chunk发送一次，包长34字节）
                                // 新增：缓冲4个chunk后合并为一包发送，以最大化包长度利用
                                // 1) 将当前chunk复制到缓冲区（按通道存放）
                                for (u16_t i = 0; i < CHUNK_SIZE; i++) {
                                        mode_3_array_t_raw[recorded_spike_channel][mode3_raw_chunk_count * CHUNK_SIZE + i] =
                                                mode_3_array_t[recorded_spike_channel * CHUNK_SIZE + i];
                                }
                                mode3_raw_chunk_count++;
                                // 2) 缓冲满4个chunk则一次性发送
                                if (mode3_raw_chunk_count >= MODE3_RAW_BUFFER_CHUNKS) {
                                        err = mode_3_raw_tx_payload_wrap(&mode_3_array_t_raw[recorded_spike_channel][0],
                                                                         CHUNK_SIZE * MODE3_RAW_BUFFER_CHUNKS,
                                                                         recorded_spike_channel);
                                        mode3_raw_chunk_count = 0; // 发送后清空计数
                                }
                                // ~ 1100 us : 10Khz
                                process_neural_signals_mode3(input_buffer, CHUNK_SIZE, 
                                                                                    decimated_buffer_LFP, mua_output, decimated_buffer_ESA);
                                // Convert LFP & ESA data from float to uint16 for transmission
                                convert_rhd2132_samples(mode_3_array_lfp_t, decimated_buffer_LFP, MODE_3_LFP_SIZE, Filter_scale, 0);
                                convert_rhd2132_samples(mode_3_array_esa_t, decimated_buffer_ESA , MODE_3_ESA_SIZE, Filter_scale, 0);
                        }
                /*** 3. ESB package organization ***/ 
                        if(sampe_mode == 0){ // lfp 
                                convert_rhd2132_samples(channel_array[0], mode_0_input_buffer,
                                                         Channel_recorded * SAMPLE_POINT_NUM * time_window,
                                                         Filter_scale, 1);
                                process_lfp_lowpass_decimate(mode_0_input_buffer, SAMPLE_POINT_NUM * time_window, mode_0_decimated_buffer);
                                convert_rhd2132_samples(mode_0_array_lfp_t, mode_0_decimated_buffer,
                                                         Channel_recorded * MODE0_DECIMATED_SAMPLES_PER_CHANNEL,
                                                         Filter_scale, 0);
                                // means if the fifo is full, the newest packets will not be added to fifo
                                err = tx_payload_wrap(mode_0_array_lfp_t, imu_data, lc_data,
                                                      (Channel_recorded * MODE0_DECIMATED_SAMPLES_PER_CHANNEL));
                                // cost 30 us in nrf-52840 to wrap one package with 96 u16_t data

                        }else if(sampe_mode == 1){ // spike: one channel raw data + raster
                                        /* for single raw channel MUA_BIN_SIZE: 18 ;SPIKE_SAMPLE_POINT_NUM: 90 */
                                        err = spike_tx_payload_wrap(spike_channel_array[recorded_spike_channel], MutiUnitActivityArray, 
                                                                        imu_data, lc_data, SPIKE_SAMPLE_POINT_NUM, recorded_spike_channel);
                        }else if(sampe_mode == 2){
                                /* send other sensor data */
                                // err = spike_sensor_tx_payload_wrap(imu_data, lc_data);
                                /* here send 4 channel spike raw data with lfp in 3 packets, without spike online detection */
                                for (int packets_nu = 0 ; packets_nu < 3; packets_nu++){ // 3 packets
                                        for(int ch=0;ch<4;ch++){ // 4 channels
                                                for (int d=0;d<data_size_per_channel_packets;d++){
                                                        temp_spike_channel_array[d + ch * data_size_per_channel_packets] = 
                                                                        spike_channel_array[spike_raw_channel[ch]][packets_nu * data_size_per_channel_packets + d];
                                                }
                                        }
                                        err = spike_multi_tx_payload_wrap(temp_spike_channel_array, sizeof(temp_spike_channel_array)/2, spike_raw_channel, (u8_t)packets_nu);
                                        k_sleep(K_USEC(435)); // 用来保证 数据传输接受会按照先后顺序
                                }

                        }else if(sampe_mode == 3){ 
                                // head + timestamp + flag + imu + battery + lfp + raster : 16 * 3 + 16 * 3 + 4 + 6 + 3 + 3 = 112
                                err = mode_3_tx_payload_wrap(mode_3_array_lfp_t, mode_3_array_esa_t, mua_output, imu_data, lc_data, MODE_3_LFP_SIZE);
                        } 
                        
                /*** 4. suspend main thread and wait to be waked up ***/
                sensor_update_flag = 0;
                if(sampe_mode == 0){ // 只在mode0下做低功耗的处理
                        k_sleep(K_FOREVER); 
                }
                //TODO 考虑使用20Hz的ESA，125Hz采样率；来实现全天候的Mode3记录;
                }
	}
        return 0;
}

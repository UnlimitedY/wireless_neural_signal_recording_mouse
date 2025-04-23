#ifndef RHDRecording_h
#define RHDRecording_h

/*
- Functions
    1. RHD initiation
    2. RHD Recording
*/

// nrfx library
#include <nrfx.h>
#include <nrfx_timer.h>
#include <nrfx_ppi.h>
#include <helpers/nrfx_gppi.h>
#include <nrfx_gpiote.h>
#include <nrfx_spim.h>
#include <zephyr/kernel.h>

#include <zephyr/logging/log.h>

/*
 * typedef
 */
typedef unsigned char u8_t;
typedef unsigned short u16_t;
typedef unsigned int u32_t;

#define GPIOE_INST NRF_DT_GPIOTE_INST(DT_NODELABEL(led0), gpios) // 获得 gpio0 这个实例
// macro define
// fortest
#define TEST_CHANNEL 16 

/***************************************SPI marco define***************************************************/
#define NRFX_SPIM_SCK_PIN 14  // 14 // aviod to use Standard drive, low frequency I/O only PIN
#define NRFX_SPIM_MOSI_PIN 5 // 5 //
#define NRFX_SPIM_MISO_PIN 4 // 4 //
#define NRFX_SPIM_SS_PIN 15	  // 15 //

// FOR  headstage test
// #define NRFX_SPIM_SCK_PIN 27 
// #define NRFX_SPIM_MOSI_PIN 30
// #define NRFX_SPIM_MISO_PIN 28
// #define NRFX_SPIM_SS_PIN 29

#define SPI_INSTANCE 3 /**< SPI instance index.SPI3 */
#define SPI_INSTANCE_INIT 2 /**< SPI instance index.SPI2 */
#define ISR_PRIORITY 2

#define time_window 1 // each time_window has 100 samples every channel;using the parameter to reduce time resolution and increase the limitation of wireless communication time.

/* for LFP 16 channels raw data */
// 19 commands as one command packet; the bin size is 100 samples every channel
#define SAMPLE_POINT_NUM 7
#define CONVERT_FASHION_NUM 20 // 16 channels + 3 dummy slots; 注意：因为rhd 读取数据有2个spi事件的延迟，所以至少需要有两个empty slots
#define SPI_TX_BUF_SIZE (CONVERT_FASHION_NUM * SAMPLE_POINT_NUM * time_window) // 7 * 16 * 2 == 224 bytes
#define SPI_RX_BUF_SIZE (CONVERT_FASHION_NUM * SAMPLE_POINT_NUM * time_window) //  bytes ;CONVERT_FASHION_NUM * 3(timer duration) * 100 == 5.1ms  ,using half of RX buffer to get achieve data process in line with data acquiration
#define m_length 2

extern u16_t init_tx_buf[1];
extern u16_t init_rx_buf[1];
// 注意： 这里*2，来防止在采样过程中偶尔出现的数据溢出问题
#define LFP_TX_BUFFER_SIZE  SPI_TX_BUF_SIZE * 2
#define LFP_RX_BUFFER_SIZE  SPI_RX_BUF_SIZE * 2
extern u16_t m_tx_buf[LFP_RX_BUFFER_SIZE]; // ppi convert command; /**< TX buffer. */
extern u16_t m_rx_buf[2][LFP_RX_BUFFER_SIZE]; /*< RX buffer. double buffer >*/

// address of spi double buffer
// extern uint32_t m_tx_buf_addr;
// extern uint32_t m_rx_buf_addr;

// all channel data array
extern u16_t channel_array_t[SAMPLE_POINT_NUM * time_window];
extern u16_t channel_array[16][SAMPLE_POINT_NUM * time_window];	 // 100 samples every channel; this data array will generate raw data packet of singe channel and the MutiUnitActivityu.

/* for spike 4 channels raw data + raster data the sample rate is about 20khz; the value of this array will be assigned every sample bin period */
#define SPIKE_SAMPLE_POINT_NUM 90 
#define SPIKE_CONVERT_FASHION_NUM 19
#define SPIKE_SPI_TX_BUF_SIZE (SPIKE_CONVERT_FASHION_NUM * SPIKE_SAMPLE_POINT_NUM)
#define SPIKE_SPI_RX_BUF_SIZE (SPIKE_CONVERT_FASHION_NUM * SPIKE_SAMPLE_POINT_NUM)

#define MUA_BIN_SIZE 18 // must be the factor of @SPIKE_SAMPLE_POINT_NUM : ~ 1ms in 17khz sampling

#define SPIKE_TX_BUFFER_SIZE  SPIKE_SPI_TX_BUF_SIZE * 2
#define SPIKE_RX_BUFFER_SIZE  SPIKE_SPI_RX_BUF_SIZE * 2

extern u16_t spike_m_tx_buf[SPIKE_TX_BUFFER_SIZE]; // ppi convert command; /**< TX buffer. */
extern u16_t spike_m_rx_buf[2][SPIKE_RX_BUFFER_SIZE]; /*< RX buffer. double buffer >*/

// address of spi double buffer
// extern uint32_t spike_m_tx_buf_addr;
// extern uint32_t spike_m_rx_buf_addr;

extern u16_t spike_channel_array_t[SPIKE_SAMPLE_POINT_NUM];
extern u16_t spike_channel_array[16][SPIKE_SAMPLE_POINT_NUM];	

extern u16_t MutiUnitActivityArray[(SPIKE_SAMPLE_POINT_NUM / MUA_BIN_SIZE)]; // 21 sample each MUA bin. 105 sample is equal to 5 bins and 16 channels correspond to 5 shorts ,given that 1bit/sample


/*************spi init***************/
extern const nrfx_spim_t spi; /**< SPI instance. */
extern const nrfx_spim_t spi_init; /**< SPI instance. */

extern volatile uint32_t spi_overflow_flag;

/***************************************RHD marco define***************************************************/
// initiation: 1KHz; LFP recording TODO
extern u16_t RHD_command;
extern const u16_t NINE_DUMMPY[9];
// ADC self-calibration command ,this command needs nine dummy command to generate the necessary clock cycles to run.
// default register setting and must be reinitiated by GUI
#define CALIBRATE 0x0055
#define CLEAR 0x006A	 // not necessary to use this command
						 // Registers configuration using write command

/************************ lfp 1khz sampling setting ************************/                         
#define lfp_Register0 0xc280 // amp fast settle is 0  ,disable ADC AND amp to reduce power
#define lfp_Register0_enable 0xde80 // amp fast settle is 0, enable ADC

#define lfp_Register1 0x2081 // VDD sense disable ,using 16 * 1 KS/s ADC
#define lfp_Register2 0x2882 // MUX bias current, configuration as above

#define lfp_Register3 0x0083 // diable tempS and digout
// absmode disable + unsigned offset binary notation ADC + weak MISO + DSP high-pass filter enable(1.2Hz upper bandwidth) // 0x9884
#define lfp_Register4 0x0084 // disable DSP
// Impedance check
#define lfp_Register5 0x0085 // Impedance check control ,which is disable
#define lfp_Register6 0x0086 // DAC output voltage ,there is 0
#define lfp_Register7 0x0087 // Impedance check electrode select, this is 0
// on-chip Amplifier bandwidth Select
//     //  using 1K Hz upper bandwidth; use on-chip programmable resistors
#define lfp_Register8 0x2e88
#define lfp_Register9 0x0289
#define lfp_Register10 0x1e8a
#define lfp_Register11 0x038b
//     //  using 1 Hz lower bandwidth; use on-chip programmable resistors
#define lfp_Register12 0x2c8c
#define lfp_Register13 0x068d
// indicidual Amplifier Power ,channel 0-15 set to one for using these channels' Amplifier
#define lfp_Register14 0xff8e
#define lfp_Register15 0xff8f
#define lfp_Register16 0x0090
#define lfp_Register17 0x0091

/************************ spike 20khz sampling setting *******************/ 
#define spike_Register0 0xc280 // amp fast settle is 0  ,disable ADC AND amp to reduce power
#define spike_Register0_enable 0xde80
#define spike_Register1 0x4281 // VDD sense disable ,using 16 * 20KS/s ADC
#define spike_Register2 0x0482 // MUX bias current, configuration as above
#define spike_Register3 0x0083 // diable tempS and digout
// #define Register4 0x8084
#define spike_Register4 0x9484 // absmode disable + unsigned offset binary notation ADC + weak MISO + DSP high-pass filter enable(308Hz upper bandwidth)
// Impedance check
#define spike_Register5 0x0085 // Impedance check control ,which is disable
#define spike_Register6 0x0086 // DAC output voltage ,there is 0
#define spike_Register7 0x0087 // Impedance check electrode select, this is 0
// on-chip Amplifier bandwidth Select
#define spike_Register8 0x1688 //  using 1Hz -7.5K Hz bandwidth
#define spike_Register9 0x8089
#define spike_Register10 0x178a
#define spike_Register11 0x808b
#define spike_Register12 0x2c8c
#define spike_Register13 0x868d
// indicidual Amplifier Power ,all set to one for using all channels' Amplifier
#define spike_Register14 0xff8e
#define spike_Register15 0xff8f
#define spike_Register16 0x0090
#define spike_Register17 0x0091

/************************ spike 20khz sampling setting without DSP*******************/ 
#define spike_raw_Register4 0x0084


extern const u16_t Register_config_lfp[18];

extern const u16_t Register_config_spike[18];

extern const nrfx_gpiote_t gpiote_instance; 

extern uint8_t gpiote_channel;

/***************************************Timer marco define***************************************************/
extern const nrfx_timer_t RHD_timer_nRFX;
extern const nrfx_timer_t SPI_timer_RESET;

extern uint32_t timer_period; // 33  us period ，2 is  30KHz ; 3 is 20KHz
extern uint32_t reset_ticks_value;

extern volatile bool spi_buff_flag;
extern volatile bool buffer_is_full;

extern u16_t sampe_mode; // lfp or spike

/***************************************PPI DMA marco define***************************************************/
extern uint8_t gp_channel_1;
extern uint8_t gp_channel_2;
extern uint8_t gp_channel_3;

extern k_tid_t mainThread;

extern bool sample_switch;
/*************************************** function ***************************************************/
uint32_t CS_Gpiote_init(void); // init gpiote: control spi cs line with ppi

u16_t swapShort16(u16_t shortValue); // swap upper byte and lower byte in a u16_t

// spi
uint32_t spim_init(void); // init spim3 

uint32_t rhdspi_init(void);

void spi_transmit_buffer_reset();

u16_t spi_trans(u16_t command);

// timer
void SPI_timer_event_handler(nrf_timer_event_t event_type, void *p_context);

uint32_t timer_init(uint32_t timer_period, uint32_t reset_ticks_value);

void timer_stop();

void timer_start();

// ppi
uint32_t ppi_init(); // TimerRHD -> SPIM3 -> GPIOTE -> TimerReset

// RHD init
u16_t Writecommand_generator(u8_t regnum, u8_t data);

u16_t Convertcommand_generator(u8_t channel, u8_t reset);

u16_t Readcommand_generator(u8_t regnum);

u16_t Calibrate();

void RHD_tx_buf_setup();

int RHD_init(const u16_t *Register_config);

#endif
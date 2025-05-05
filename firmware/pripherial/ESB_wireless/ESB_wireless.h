#ifndef ESBWIRELESS_H
#define ESBWIRELESS_H

#include <zephyr/drivers/clock_control.h>
#include <zephyr/drivers/clock_control/nrf_clock_control.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/irq.h>
#include <nrf.h>
#include <esb.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/kernel.h>
#include <zephyr/types.h>


/*
 * typedef
 */
typedef unsigned char u8_t;
typedef unsigned short u16_t;
typedef unsigned int u32_t;

extern bool sample_switch;
extern bool mode_switch_flag;
extern u16_t sampe_mode;
extern u32_t tx_payload_wraped_num;

extern uint32_t packet_sent_counter[2]; // count the sent package number: [0] is success; [1] is fail
extern u8_t HABITS_events; // define the events of HABITS

extern u8_t raw_channel[16]; // define which channels used
extern u8_t recorded_channel_num; // lfp raw data: channel number

extern u8_t spike_raw_channel[4]; // spike raw data: channel index: maximum 4 channels recorded 
extern u8_t recorded_spike_channel; // spike raw data: mode 1

extern bool overflow_signal;
extern uint64_t stamp_check; // real-time timestamp from the power-up

extern bool sensor_update_flag; // flag of the sensor data is updated

extern u16_t threshold_list[16];

#define rf_channel_num 6
extern uint8_t rf_channel_list[rf_channel_num]; // list of channels
extern uint8_t rf_channel_rssi_list[rf_channel_num]; // list of channels
extern uint8_t bitrate; 
extern uint8_t rf_channel;

#define _RADIO_SHORTS_COMMON                                       \
	(RADIO_SHORTS_READY_START_Msk | RADIO_SHORTS_END_DISABLE_Msk | \
	 RADIO_SHORTS_ADDRESS_RSSISTART_Msk |                          \
	 RADIO_SHORTS_DISABLED_RSSISTOP_Msk)

// note: struct esb_payload.data needs to be changed to u16_t, and the length parameter still represents bytes
extern struct esb_payload rx_payload; // command & behavioral events --rx
extern struct esb_payload tx_payload; // neural signal -- tx

extern struct esb_payload empty_payload; // when sampling disable 
extern struct esb_payload timestamp_payload; // neural signal alignment required


/****************************************alignment with HABITS****************************************/
/*
* 软件对齐系统 （基于ESB）: 相当于每一次重启都是一个新的trial：每次重新开始sample的时候，做一次对齐；发送一个下位机这一次重启经历的时间，上位机将这个时间
* 在数据收集过程中，无法对齐实际时间和收到包的时间由于数据发送的延时和丢包问题，需要每次重启的时候，做一次单独的时间对齐到重启的实际时间
* 当GUI 重启的时候，会丢失这个对齐的值，需要保存一个文件来单独记录这个对齐的值
* HABITS 使用实际物理时间，同时LTNSRS 也使用实际物理时间 来对齐
* 注意：必须每次重启后都需要通过上位机来打开sample，才能实现时间的对齐而不出现bug
*/
extern u32_t packet_timestamp; // define the unique packet index: timestamp
extern uint32_t timestamp_LTNSRS; // packed timestamp from LTNSRS (long-term neural signal recording system)

// not use
extern uint32_t timestamp_HABITS; // received timestamp from HABITS
extern uint32_t timestamp_baseline; // baseline timestamp updated by alignment events

/*****************************ESB function***************************************/
// esb init
int clocks_start(void);
int esb_initialize(void);

// esb params alignment
int esb_shake_hand_request(void);
int esb_shake_hand_received(void);

int esb_rf_channel_scan(void);

// esb callback
void event_handler(struct esb_evt const *event);
void command_process(uint8_t length, uint16_t *data); // command process & behavioral events & behavioral timestamps

// timestamp_payload wrap function: every sample onset
int timestamp_payload_wrap(void);
// empty_payload wrap function: when sample stopping
int empty_payload_wrap(void);
// tx_payload wrap function: when sample working mode 0
int tx_payload_wrap(u16_t *Raw_data, int16_t *imu_data, int16_t *lc_data, u16_t raw_length);
// tx_payload wrap function: when sample working: mode 1
int spike_tx_payload_wrap(u16_t *Spike_Raw_data, u16_t *Spike_raster_data, int16_t *imu_data, int16_t *lc_data,  u16_t spike_raw_length, u8_t packet_index);
// mode 2
int spike_multi_tx_payload_wrap(u16_t *Spike_Raw_data, u16_t spike_raw_length, u8_t *packet_index, u8_t counter);
int spike_sensor_tx_payload_wrap(int16_t *imu_data, int16_t *lc_data);

#endif
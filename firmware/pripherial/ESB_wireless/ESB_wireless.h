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

extern u32_t packet_timestamp; // define the unique packet index: timestamp
extern u32_t packet_sent_counter[2]; // count the sent package number: [0] is success; [1] is fail
extern u8_t HABITS_events; // define the events of HABITS

extern u8_t raw_channel[16]; // define which channels used
extern u8_t recorded_channel_num; // lfp raw data: channel number

extern u8_t spike_raw_channel[4]; // spike raw data: channel index: maximum 4 channels recorded 
extern u8_t recorded_spike_channel; // spike raw data: mode 1

extern bool overflow_signal;
extern uint64_t stamp_check; // real-time timestamp from the power-up

extern bool sensor_update_flag; // flag of the sensor data is updated

extern u16_t threshold_list[16];

#define _RADIO_SHORTS_COMMON                                       \
	(RADIO_SHORTS_READY_START_Msk | RADIO_SHORTS_END_DISABLE_Msk | \
	 RADIO_SHORTS_ADDRESS_RSSISTART_Msk |                          \
	 RADIO_SHORTS_DISABLED_RSSISTOP_Msk)

// note: struct esb_payload.data needs to be changed to u16_t, and the length parameter still represents bytes
extern struct esb_payload rx_payload; // command & behavioral events --rx
extern struct esb_payload tx_payload; // neural signal -- tx

extern struct esb_payload empty_payload; // when sampling disable 
extern struct esb_payload timestamp_payload; // neural signal alignment required

/*****************************ESB function***************************************/
// esb init
int clocks_start(void);

int esb_initialize(void);

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
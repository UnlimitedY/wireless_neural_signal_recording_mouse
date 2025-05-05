#include "ESB_wireless.h"
#include <zephyr/logging/log.h>
#define LOG_MODULE_NAMEs LFP_Recording_peripherials
LOG_MODULE_REGISTER(LOG_MODULE_NAMEs);

int clocks_start(void)
{
	int err;
	int res;
	struct onoff_manager *clk_mgr;
	struct onoff_client clk_cli;

	clk_mgr = z_nrf_clock_control_get_onoff(CLOCK_CONTROL_NRF_SUBSYS_HF);
	if (!clk_mgr) {
		// LOG_ERR("Unable to get the Clock manager");
		return -ENXIO;
	}

	sys_notify_init_spinwait(&clk_cli.notify);

	err = onoff_request(clk_mgr, &clk_cli);
	if (err < 0) {
		// LOG_ERR("Clock request failed: %d", err);
		return err;
	}

	do {
		err = sys_notify_fetch_result(&clk_cli.notify, &res);
		if (!err && res) {
			// LOG_ERR("Clock could not be started: %d", res);
			return res;
		}
	} while (err);

	// LOG_DBG("HF clock started");
	return 0;
}

int esb_initialize(void)
{
	int err;
	/* These are arbitrary default addresses. In end user products
	 * different addresses should be used for each set of devices.
	 */
    // pipe 0 的base addr， 注意不能使用0x55和0xAA，这两个是preamble（1 byte）所使用的的地址 4bytes
	uint8_t base_addr_0[4] = {0xE7, 0xE7, 0xE7, 0xE7};
    // pipe 1-7 的base addr 4 bytes
	uint8_t base_addr_1[4] = {0xC2, 0xC2, 0xC2, 0xC2};
    // 8个pipes 所使用的的唯一的prefix 1 byte 的地址
	uint8_t addr_prefix[8] = {0xE7, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8};

	struct esb_config config = ESB_DEFAULT_CONFIG;

    // 注意： 使用ESB 模式，ACK不能附带payload，不能进行全双工的数据传输
	config.protocol = ESB_PROTOCOL_ESB_DPL; // 设置 传输数据的protocol ,可以选择固定长度的payload length还是动态变化的长度
	config.retransmit_delay = 1800; // 重传的时间延迟 us； 在接收端失效下，450 和600的值产生的failed tx events数量是一样的; 不能太短也不能太长
    /*
    * 注意： 必须要使用2mbps，否则会导致esb 占用cpu资源过多导致 休眠时间不足而功耗剧烈上升；即使1mbps 能增加稳定性
    */
	config.bitrate = ESB_BITRATE_2MBPS; // 设置 传输速率
	config.event_handler = event_handler; // 设置传送的事件的回调函数
	config.mode = ESB_MODE_PTX; // 设置这台机子是工作在上面mode上 ，ptx or prx ,一般对应多台ptx ,一台prx
	config.selective_auto_ack = true; // enable ack 
    // enable fast ramp up: 40us: 
    // 注意这里必须要保证接收双方要是nrf52以上系列的；如果不是，或者接收端ack离线，会导致ptx一直处于ESB_STATE_PTX_RX_ACK状态
    config.use_fast_ramp_up = false;  // 为了保证 稳定这里 disable fast ramp up
    config.retransmit_count = 1; // the times of retransmit
    // 注意：在ack 模式下，retransmit 失败以后，并不会把fifo清空。这相当于是一个绝对的fifo
    // 同时tx suspended，需要等待下一个发送命令;(注意这里需要esb_start_tx()命令，auto模式下只会返回错误)
    // TODO 最好使用esb_flush_tx()来构建一个相对的fifo；并且 合理使用esb_start_tx()来避免发送时间的浪费
    config.tx_mode = ESB_TXMODE_AUTO; 

	err = esb_init(&config);
	if (err) {
		return err;
	}

	err = esb_set_base_address_0(base_addr_0); // 设置esb的传输地址，一个esb可以同时与8个tx进行通信 ,即8个pipes
	if (err) {
		return err;
	}

	err = esb_set_base_address_1(base_addr_1);
	if (err) {
		return err;
	}

	err = esb_set_prefixes(addr_prefix, ARRAY_SIZE(addr_prefix));
	if (err) {
		return err;
	}

    // 这个会影响传输重发率和通信距离；在极限的设置下，目前custom board的esb通信距离在20cm左右；而且不能有障碍物；
	esb_set_tx_power(ESB_TX_POWER_0DBM); 
    // esb_set_tx_power(ESB_TX_POWER_NEG4DBM); 

    esb_set_rf_channel(84); 
	return 0;
}

void command_process(uint8_t length, uint16_t *data)
{
    /*
    * 1. RX_data : head (1 u16_t) + data (n u16_t)
    * 2. head includes: 
    *   - system commands:
    *   1. (Launch sampling): 0001
    *   2. (Dummary): 0000
    *   3. (disable sampling): 0002
    *   4. (low power): 0003
    * 
    *   - behavioral events
    *   1. (spike recording): 0100 (TODO) + data (RHD reconfigration)
    *   2. (LFP channels switch): 0200 + data (recording channels indice) 
    *       [config the registers of RHD to disable not used channels]
    *   3. (Impedance check): 0400 (TODO) 
    *   - alignment signal
    *   1. (HABITS events): 0300 (switch sample mode)
    */
	
    u16_t command_head = data[0];

    switch (command_head)
    {
    case 0x0001: // begin sampling
    {
        if (!sample_switch) // when the sample is paused
        {
            sample_switch = true;
        }
    }
        break;
    case 0x0002: // disable sampling
    {
        if (sample_switch)
        {
            sample_switch = false;
        }
    }
        break;
    case 0x0003: // low-power mode: diff-level
    {
        // disable everything
        sample_switch = false;
        // TODO
    }
        break;


    case 0x0200: // LFP channels switch
    {
        recorded_channel_num = 0;
        for (int i=0;i<16;i++){
            if((u8_t)data[1 + 1] < 16){
                raw_channel[i] =  data[i+1];
                recorded_channel_num++;
            }
        }
        // RHD command acording to raw_channel to enable/disable amplifers; other do not need change
        // TODO
    }
        break;
    case 0x0300: // behavioral event-triggered tasks (change mode): GUI & HABITS
    {
        mode_switch_flag = true;
        sample_switch = false;
        if((u8_t)data[1] < 3){
            sampe_mode = data[1];
        }
    }
        break;
    case 0x0400: // spike mode 1: raw channel selection
    {
        if((u8_t)data[1] < 16){
            recorded_spike_channel = (u8_t)data[1];
            threshold_list[recorded_spike_channel] = data[2];
        }
    }
        break;
    case 0x0500: // spike mode 2: 4 raw channel selection
    {
        for(int i=1; i<5 ; i++){
            if((u8_t)data[i] < 16){
                spike_raw_channel[i-1] = (u8_t)data[i];
            }
        }
    }
        break;
    default:
        break;
    }

}

void event_handler(struct esb_evt const *event)
{
	switch (event->evt_id) {
	case ESB_EVENT_TX_SUCCESS:
		packet_sent_counter[0]++;
		break;
	case ESB_EVENT_TX_FAILED:
		packet_sent_counter[1]++;
		break;
	case ESB_EVENT_RX_RECEIVED:
        {
        packet_sent_counter[0]++;
		while (esb_read_rx_payload(&rx_payload) == 0) {
            command_process(rx_payload.length, rx_payload.data);
		}
        }
		break;
	}
}

/*
* scan : return rssi value (weights) of channel list
*/
int esb_rf_channel_scan(void){
    if(!esb_is_idle()){
        return -1;
    }
    int rssi_reading = 0;
    uint8_t minimum_rssi_index = 0;
    uint8_t minimum_rssi = 0;

    for(int i=0;i<sizeof(rf_channel_list);i++){
        esb_set_rf_channel(rf_channel_list[i]);
        esb_start_rx();
        k_sleep(K_USEC(300)); // wait for booting up

        rssi_reading = 0;
        for(int j = 0; j < 10; j ++)
        {
            NRF_RADIO->TASKS_RSSISTART = 1;
            while(NRF_RADIO->EVENTS_RSSIEND == 0);
            rssi_reading += NRF_RADIO->RSSISAMPLE;
             k_sleep(K_USEC(100));
        }
        esb_stop_rx();
        k_sleep(K_USEC(300));
        rf_channel_rssi_list[i] = rssi_reading/10;

        if(minimum_rssi < rf_channel_rssi_list[i]){
            minimum_rssi_index = i;
            minimum_rssi = rf_channel_rssi_list[i];
        }
        
    }

    esb_set_rf_channel(rf_channel_list[rf_channel]);
    return minimum_rssi_index; 
}

/*
* select channel and bitrate
*/
int esb_shake_hand_request(void){
    // check if the esb is idle but fifo not empty, which means the retranmition failed
    if(esb_is_idle() && !esb_tx_empty()){
        // send a packet (request) with params    
        // change the front packets
        u8_t channel_temp;
        if(rf_channel < 5){
            channel_temp = rf_channel_list[rf_channel + 1];
        }else{
            channel_temp = rf_channel_list[0];
        }
        esb_tx_front_channel(channel_temp);
    }
}

int esb_shake_hand_received(void){
    // check if request success, change the params
    if(!esb_tx_empty()){
    // TODO
    }
}


int timestamp_payload_wrap(void){
    timestamp_payload.noack = 0;
    stamp_check = k_uptime_get();
    // stamp_check = (uint64_t)k_cyc_to_ms_near32(k_cycle_get_32());
    for (int i = 0; i < 4; i++)
    {
        timestamp_payload.data[4 - i] = (stamp_check >> (i * 16)) & 0xFFFF;
    }
    timestamp_payload.data[0] = 0x0300;	// payload type		
    timestamp_payload.data[5] = ((u16_t)rf_channel_rssi_list[rf_channel]) << 8 | (u16_t)rf_channel_list[rf_channel];
    return esb_write_payload(&timestamp_payload); 
}

int empty_payload_wrap(void){
    empty_payload.data[0] = 0x0400; // empty type
    empty_payload.data[1]++;		   // some information needed to upload
    empty_payload.noack = 0; 
    return esb_write_payload(&empty_payload); // wirte 对应 tx ,将packet加入到tx buffer中
}

int tx_payload_wrap(u16_t *Raw_data, int16_t *imu_data, int16_t *lc_data, u16_t raw_length){ // LFP recording
    tx_payload.noack = 0;

    u16_t txbufIndex = 0; // count the length of one tx_payload package
    // 1. pre-head of packet 0xXXYY---XX is rf_channel; YY is the number of recorded channels
    tx_payload.data[0] = 0x0100 | recorded_channel_num; 
    // 2. package signal including: real-time timestamp; overflow_signal
    tx_payload.data[2] = (u16_t)timestamp_LTNSRS; 
    tx_payload.data[1] = (u16_t)(timestamp_LTNSRS >> 16);
    tx_payload.data[3] = ((u16_t)sensor_update_flag << 8) | (u16_t)overflow_signal; 
    txbufIndex += 4;

    // 3. twi data:  6-acc or 3-acc data 
    for (int i = 0; i < 6; i++)
    {
        tx_payload.data[txbufIndex + i] = (int16_t)*(imu_data + i);
    }
    txbufIndex += 6;

    // 4. BatterPower data: fixed 3 u16_t
    for (int i = 0; i < 3; i++)
    {
        tx_payload.data[txbufIndex + i] = (int16_t)*(lc_data + i);
    }
    txbufIndex += 3;

    // 5. LFP raw data 16 channel 2KHz -> 32KHz ; length: 16 * 7 = 112 points 
   
    for (int i = 0; i < raw_length; i++)
    { 
        tx_payload.data[txbufIndex + i] = (u16_t)*(Raw_data + i);
    }
    txbufIndex += raw_length;
  
    tx_payload.length = txbufIndex * 2; //  224 + 26 == 250 bytes; maximum 252 bytes
    return esb_write_payload(&tx_payload); 
}

int spike_tx_payload_wrap(u16_t *Spike_Raw_data, u16_t *Spike_raster_data, int16_t *imu_data, int16_t *lc_data, u16_t spike_raw_length, u8_t packet_index){
    tx_payload.noack = 0;

    u16_t txbufIndex = 0; // count the length of one tx_payload package
    // 1. pre-head of packet 0xXXYY---XX is type; YY is the index of recorded channels
    tx_payload.data[0] = 0x0200 | packet_index; 
    // 2. package signal including: real-time timestamp; overflow_signal
    tx_payload.data[2] = (u16_t)timestamp_LTNSRS; 
    tx_payload.data[1] = (u16_t)(timestamp_LTNSRS >> 16);
    tx_payload.data[3] = ((u16_t)sensor_update_flag << 8) | (u16_t)overflow_signal; 
    txbufIndex += 4;

    // 3. twi data:  6-acc or 3-acc data 
    for (int i = 0; i < 6; i++)
    {
        tx_payload.data[txbufIndex + i] = (int16_t)*(imu_data + i);
    }
    txbufIndex += 6;

    // 4. BatterPower data: fixed 3 u16_t
    for (int i = 0; i < 3; i++)
    {
        tx_payload.data[txbufIndex + i] = (int16_t)*(lc_data + i);
    }
    txbufIndex += 3;

    // 5. spike raw data 1 channel length: 105
    for (int i = 0; i < spike_raw_length; i++)
    { 
        tx_payload.data[txbufIndex + i] = (u16_t)*(Spike_Raw_data + i);
    }
    txbufIndex += spike_raw_length;
    
    // 6. spike raster data 5 shorts
    for (int i = 0; i < 5; i++)
    { 
        tx_payload.data[txbufIndex + i] = (u16_t)*(Spike_raster_data + i);
    }
    txbufIndex += 5;

    tx_payload.length = txbufIndex * 2; //  90 * 2 + 5 * 2 + 13 * 2 == 216 bytes; maximum 252 bytes
    return esb_write_payload(&tx_payload); 
}

/**************************mode 2**********************/
int spike_multi_tx_payload_wrap(u16_t *Spike_Raw_data, u16_t spike_raw_length, u8_t *packet_index, u8_t counter){
    tx_payload.noack = 0; // ack; 注意，没有ack 会导致大约1% 的丢包 

    u16_t txbufIndex = 0; // count the length of one tx_payload package
    // 1. pre-head of packet 0xXXYY---XX is type; YY is the index of recorded channels
    tx_payload.data[0] = 0x0500 | counter;  
    // 2. package signal including: real-time timestamp; overflow_signal
    tx_payload.data[2] = (u16_t)timestamp_LTNSRS; 
    tx_payload.data[1] = (u16_t)(timestamp_LTNSRS >> 16);
    tx_payload.data[3] = (u16_t)overflow_signal; 
    txbufIndex += 4;

    // 3. channel indice
    tx_payload.data[txbufIndex] = ((u16_t)*(packet_index) << 8) | (u16_t)*(packet_index + 1); // the first and the second channels
    tx_payload.data[txbufIndex + 1] = ((u16_t)*(packet_index + 2) << 8) | (u16_t)*(packet_index + 3); // the third and the fourth channels
    txbufIndex += 2;

    // 4. spike raw data 4 channels length: 120
    for (int i = 0; i < spike_raw_length; i++)
    { 
        tx_payload.data[txbufIndex + i] = (u16_t)*(Spike_Raw_data + i);
    }
    txbufIndex += spike_raw_length;

    tx_payload.length = txbufIndex * 2; //  (4 + 2 + 120) * 2 == 252 bytes; maximum 252 bytes
    return esb_write_payload(&tx_payload); 
}

int spike_sensor_tx_payload_wrap(int16_t *imu_data, int16_t *lc_data){
    tx_payload.noack = 0;

    u16_t txbufIndex = 0; // count the length of one tx_payload package
    // 1. pre-head of packet 0xXXYY---XX is type; YY is the index of recorded channels
    tx_payload.data[0] = 0x0600; 
    // 2. package signal including: real-time timestamp; overflow_signal
    tx_payload.data[2] = (u16_t)timestamp_LTNSRS; 
    tx_payload.data[1] = (u16_t)(timestamp_LTNSRS >> 16);
    tx_payload.data[3] = ((u16_t)sensor_update_flag << 8) | (u16_t)overflow_signal; 
    txbufIndex += 4;

    // 3. twi data:  6-acc or 3-acc data 
    for (int i = 0; i < 6; i++)
    {
        tx_payload.data[txbufIndex + i] = (int16_t)*(imu_data + i);
    }
    txbufIndex += 6;

    // 4. BatterPower data: fixed 3 u16_t
    for (int i = 0; i < 3; i++)
    {
        tx_payload.data[txbufIndex + i] = (int16_t)*(lc_data + i);
    }
    txbufIndex += 3;

    tx_payload.length = txbufIndex * 2; // (4 + 6 + 3) * 2 == 26 bytes; maximum 252 bytes
    return esb_write_payload(&tx_payload); 

}
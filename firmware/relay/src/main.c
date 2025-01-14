/*
 * ESB version LFP central 接收多个下位机上传来的数据并进行数据的预处理通过串口发送到PC
 * 同时接收PC和HABITS通过串口下发的命令，并通过ESB发送给不同的下位机,主要的作用就是实时的转发下位机与上位机之间的数据流动
 * 使用arduino 来作为盾板， spi传输到teensy上，再由teensy上传到PC
 */
#include <zephyr/drivers/clock_control.h>
#include <zephyr/drivers/clock_control/nrf_clock_control.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/irq.h>
#include <zephyr/logging/log.h>
#include <nrf.h>
#include <esb.h>
#include <zephyr/types.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <nrfx_usbd.h>
#include <stdio.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/usb/usb_device.h>
#include <zephyr/usb/usbd.h>

#include <zephyr/sys/ring_buffer.h>

typedef unsigned char u8_t;
typedef unsigned short u16_t;
typedef unsigned int u32_t;

#define LOG_MODULE_NAME LFP_Recording_central
LOG_MODULE_REGISTER(LOG_MODULE_NAME, LOG_LEVEL_INF); 

#define LED0_NODE DT_ALIAS(led0) 
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

#define USBTX_PACKETS_SIZE 10 // 10 packets per uart send：no matter the kind of packets

#define RING_BUF_SIZE USBTX_PACKETS_SIZE * 252 * 2
struct ring_buf ringbuf;
u8_t ring_buffer[RING_BUF_SIZE];

/*****************for alignment*****************/
// timestamp Habits: get from PC
uint32_t timestamp_HABITS = 0;

/**************************************** esb setup********************************************************/
u16_t drop_packets_num = 0;
int free_size_ringbuff = 0;
int recv_len_esb;

u16_t esb_packets_length = 0;
u8_t tx_buffer_temp[USBTX_PACKETS_SIZE * 252 + 1000]; // 注意：这个决定了一次传输包的最大数量
int packets_accumul = 0;
int packets_accumul_num = 0;

u8_t timestamp_alignment_buffer[1000];
u8_t usb_packets_address[8] = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26 ,0x27, 0x28};

// for test
int last_packet_counter[2] = {0, 0};

static struct esb_payload rx_payload; // central rx buffer // 注意这里的esb 也是u16_t
static struct esb_payload tx_payload; // command buffer

u16_t rx_temp_payload[130];

static int send_len = 0; // recording the number of data usb sent
static int counter_loop = 0; // recording the number of packages

int rf_channel = 0;
bool channel_switch = false;
k_tid_t mainThread;

int retssss;
/**************************************** usb cdc function********************************************************/
const struct device *dev;

static void interrupt_handler(const struct device *dev, void *user_data) // UART read callback from PC
{
	ARG_UNUSED(user_data);
	int esb_tx_err;
	while (uart_irq_update(dev) && uart_irq_is_pending(dev))
	{
		/* rx buffer data from PC */
		if (uart_irq_rx_ready(dev)) 
		{
			int recv_len; // number of usb read from PC
			uint8_t Command_from_PC[16]; // using 16 bytes (1 command + 7 data) as the max command data length
			recv_len = uart_fifo_read(dev, tx_payload.data, sizeof(Command_from_PC)); 
			if (recv_len < 0)
			{ // cannot read command from PC
				recv_len = 0;
				LOG_INF("Failed to read commands from PC! /n");
			}else{
				// intermediately transmit the command to peripheral
				tx_payload.length = recv_len;
				esb_tx_err = esb_write_payload(&tx_payload); 
				if (esb_tx_err)
				{
					esb_flush_tx();
					LOG_INF("Failed to send commands to peripheral! /n");
				}
			}
			
		}
	}
}

/****************************************esb PRX function********************************************************/
void event_handler(struct esb_evt const *event) // deal the receive event and add payload to ACK
{
	switch (event->evt_id)
	{
	case ESB_EVENT_TX_SUCCESS:
		break;
	case ESB_EVENT_TX_FAILED:
		break;
	case ESB_EVENT_RX_RECEIVED:
	{
	while(esb_read_rx_payload(&rx_payload)==0){
			if(rx_payload.length > 0){
				counter_loop++;

				// timestamp alignment
				if(rx_payload.data[0] == 0x0300){
					rx_payload.data[rx_payload.length/2] = rx_payload.rssi;
					rx_payload.data[rx_payload.length/2 + 1] = 0x2221;
					rx_payload.data[rx_payload.length/2 + 2] = 0x2423;
					rx_payload.data[rx_payload.length/2 + 3] = 0x2625;
					rx_payload.data[rx_payload.length/2 + 4] = 0x2827;
					send_len = uart_fifo_fill(dev, rx_payload.data, rx_payload.length + 10);

					// set channel
					rf_channel = (u8_t)rx_payload.data[5];
					channel_switch=true;
					k_wakeup(mainThread);
					continue;
				}

				if(counter_loop % 500 == 0){
					gpio_pin_toggle_dt(&led);
				}

				memcpy(rx_temp_payload, rx_payload.data, rx_payload.length);
				// define the code to seqarate the individual packages
				// rssi 
				rx_temp_payload[rx_payload.length/2] = rx_payload.rssi;
				rx_temp_payload[rx_payload.length/2 + 1] = 0x2221;
				rx_temp_payload[rx_payload.length/2 + 2] = 0x2423;
			
				esb_packets_length = rx_payload.length + 6;
				// get the free size of ring buff
				free_size_ringbuff = ring_buf_space_get(&ringbuf); // in bytes
				if(free_size_ringbuff < esb_packets_length){
					drop_packets_num++;
				}
				else{ // put the received data to ring buff
					recv_len_esb = ring_buf_put(&ringbuf, rx_temp_payload, esb_packets_length);
					if (recv_len_esb < esb_packets_length) {
						// LOG_INF("ringbuff put error!");
					}
				}
				// send to pc
				packets_accumul += esb_packets_length; 
				packets_accumul_num++;
				if((RING_BUF_SIZE - ring_buf_space_get(&ringbuf) >= packets_accumul) && (packets_accumul_num >= USBTX_PACKETS_SIZE)){
					recv_len_esb = ring_buf_get(&ringbuf, tx_buffer_temp, packets_accumul);
					if (recv_len_esb != packets_accumul) {
						// LOG_INF("Ring buffer get fail %d!", recv_len_esb);
					}else{
						// define the code to seqarate the individual group of packages
						tx_buffer_temp[packets_accumul] = 0x25;
						tx_buffer_temp[packets_accumul + 1] = 0x26;
						tx_buffer_temp[packets_accumul + 2] = 0x27;
						tx_buffer_temp[packets_accumul + 3] = 0x28;
						packets_accumul = packets_accumul + 4;

						// 注意：这里fifo满之后可能会发送不足一个包的数量导致包数据从中间截断，在pc 端丢弃这个包
						send_len = uart_fifo_fill(dev, tx_buffer_temp, packets_accumul);
						if(send_len !=  packets_accumul){
							// LOG_INF("send err %d %x %x \n" ,send_len,  tx_buffer_temp[packets_accumul - 10], tx_buffer_temp[packets_accumul - 9]);
						}
						packets_accumul = 0;
						packets_accumul_num = 0;
					}
				}
			}
		}
	break;
	}
	}
}

int clocks_start(void)
{
	int err;
	int res;
	struct onoff_manager *clk_mgr;
	struct onoff_client clk_cli;


	clk_mgr = z_nrf_clock_control_get_onoff(CLOCK_CONTROL_NRF_SUBSYS_HF);
	if (!clk_mgr)
	{
		printk("Unable to get the Clock manager");
		return -ENXIO;
	}

	sys_notify_init_spinwait(&clk_cli.notify);

	err = onoff_request(clk_mgr, &clk_cli);
	if (err < 0)
	{
		printk("Clock request failed: %d", err);
		return err;
	}

	do
	{
		err = sys_notify_fetch_result(&clk_cli.notify, &res);
		if (!err && res)
		{
			printk("Clock could not be started: %d", res);
			return res;
		}
	} while (err);
	printk("HF clock started");
	return 0;
}

int esb_initialize(void)
{
	int err;
	/* These are arbitrary default addresses. In end user products
	 * different addresses should be used for each set of devices.
	 */
	uint8_t base_addr_0[4] = {0xE7, 0xE7, 0xE7, 0xE7};
	uint8_t base_addr_1[4] = {0xC2, 0xC2, 0xC2, 0xC2};
	uint8_t addr_prefix[8] = {0xE7, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8};

	struct esb_config config = ESB_DEFAULT_CONFIG;

	config.protocol = ESB_PROTOCOL_ESB_DPL;
	config.bitrate = ESB_BITRATE_2MBPS; 
	config.mode = ESB_MODE_PRX;
	config.event_handler = event_handler;
	config.selective_auto_ack = true; // 需要两边的该参数都需要为true 才能使能noack参数
	// config.payload_length = 252;

	err = esb_init(&config);
	if (err)
	{
		return err;
	}

	err = esb_set_base_address_0(base_addr_0);
	if (err)
	{
		return err;
	}

	err = esb_set_base_address_1(base_addr_1);
	if (err)
	{
		return err;
	}

	err = esb_set_prefixes(addr_prefix, ARRAY_SIZE(addr_prefix));
	if (err)
	{
		return err;
	}
	esb_set_tx_power(ESB_TX_POWER_4DBM);

	esb_set_rf_channel(84);
	return 0;
}


/**************************************** main function********************************************************/
int main(void)
{
	int err;
	mainThread = k_sched_current_thread_query();
	/*************LED setup***************/
	if (!gpio_is_ready_dt(&led)) {
                LOG_INF("failed");
		return 0;
	}
	err = gpio_pin_configure_dt(&led, GPIO_OUTPUT_ACTIVE);
	if (err < 0) {
		return 0;
	}

	LED_hinting(200, 10);


	/* ESB setup */
	
	err = clocks_start();
	if (err)
	{
		return;
	}
	err = esb_initialize();
	if (err)
	{
		LOG_INF("ESB initialization failed, err %d", err);
		return;
	}

	err = esb_start_rx();
	if (err)
	{
		printk("RX setup failed, err %d", err);
		return;
	}

	rx_payload.pipe = 0;
	tx_payload.pipe = 0;

	
	/* usb cdc setup */ 
	int ret;

	dev = DEVICE_DT_GET_ONE(zephyr_cdc_acm_uart);
	if (!device_is_ready(dev))
	{
		printk("CDC ACM device not ready");
		return;
	}
	ret = usb_enable(NULL);
	if (ret != 0)
	{
		printk("Failed to enable USB");
		return;
	}
	/* ringbuff init */
	ring_buf_init(&ringbuf, sizeof(ring_buffer), ring_buffer);

	/* Wait 1 sec for the host to do all settings */
	k_busy_wait(1000000);

	uart_irq_callback_set(dev, interrupt_handler);
	// enable the rx irq to recieve the command
	uart_irq_rx_enable(dev);


	// main loop
	while (true){

		if(channel_switch){
			channel_switch = false;
			ret = esb_stop_rx();
			ret = esb_set_rf_channel(rf_channel);
			ret = esb_start_rx();
		}

		k_sleep(K_FOREVER);
	} // main loop 

	return 0;
}
// 在uart buffer 溢出了之后，就等一段时间再进行发送，以免出现问题
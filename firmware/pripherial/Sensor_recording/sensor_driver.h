#ifndef sensor_driver_h
#define sensor_driver_h

#include <nrfx_twim.h>
#include <nrfx_spim.h>
#include <nrfx.h>

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/i2c.h>

/* working in blocking mode for LC or mp2710 */
/* spi for lsm */
/*Pin Definitions*/

#define I2C0_NODE DT_NODELABEL(i2c0)
#define LC_SDA_PIN             25 //  25 for omnetics 22 for other
#define LC_SCL_PIN             22 //  22 for omnetics 25 for other

#define LSM_CS_PIN              NRF_GPIO_PIN_MAP(0, 28) // 28 for omnetics  30 for other
#define LSM_SCL_PIN             NRF_GPIO_PIN_MAP(0, 30) // NRF_GPIO_PIN_MAP(0, 1) for other  30 for omnetics
#define LSM_SDI_PIN             NRF_GPIO_PIN_MAP(0, 8) // Data input: MOSI
#define LSM_SDO_PIN             NRF_GPIO_PIN_MAP(1, 9) // Data output: MISO: PIN 1.09 32 + 9

#define TWI_MAX_NUM_TX_BYTES 14
#define TWI_TIMEOUT 20000 // waiting time

/* TWI instance ID. */
#define LC_INSTANCE_ID      0 // using the twi 0
/* SPI instance ID. */
#define LSM_INSTANCE_ID     1 // using the twi 1

/* TWI instance. */ // lsm 可以工作在400k和100k模式下；但需要外部上拉电阻
extern const nrfx_twim_t lc_twim;
extern uint8_t twimWriteDataBuffer[TWI_MAX_NUM_TX_BYTES];
extern uint8_t LCDataBuffer[6];
/* SPI instance. */
extern const nrfx_spim_t lsm_spi; /**< SPI instance. */

/*************************************functions******************************************/
nrfx_err_t twim_init (void); // not use when using device tree configration

// for MP2710 battery charge
bool MP2170_twi_data_write(uint8_t slaveAddr, uint8_t regAddr, uint8_t pData);

nrfx_err_t MP2170_twi_data_read(uint8_t slaveAddr, uint8_t regAddr, uint8_t *pData);

// for LC
uint8_t cal_crc_table(uint8_t *data, uint8_t len);

uint8_t cal_bytes_crc8(uint8_t *data, uint8_t len);

void lc_twim_handler(nrfx_twim_evt_t const * p_event, void * p_context);

bool LC_twi_data_write(uint8_t slaveAddr, uint8_t regAddr, uint16_t pData);

nrfx_err_t LC_twi_data_read(uint8_t slaveAddr, uint8_t regAddr, uint16_t *pData);

// spi: lsm
nrfx_err_t lsm_spim_init(void);

void mergeRegisterAndData(uint8_t *pTxBuf, uint8_t regAddr, uint8_t *pData, uint8_t dataLen);

nrfx_err_t data_write(uint8_t regAddr, uint8_t *pData, uint8_t dataLen, uint8_t device);

nrfx_err_t data_read(uint8_t regAddr, uint8_t *pData, uint8_t dataLen, uint8_t device);

/*******************************************************************************/
#endif
#include "sensor_driver.h"

/* working in non-blocking mode, TXRX only can work under this mode*/

// void twim_enable(void)
// {
//     // nrfx_twim_enable(&lsm_twim);
//     // nrfx_twim_enable(&lc_twim);
// }

// void twim_disable(void)
// {
//     // nrfx_twim_disable(&lsm_twim);
//     // nrfx_twim_disable(&lc_twim);
// }

/**
 * @brief merge the register address with the data
 */
void mergeRegisterAndData(uint8_t *pTxBuf, uint8_t regAddr, uint8_t *pData, uint8_t dataLen)
{
    pTxBuf[0] = regAddr;
    memcpy((pTxBuf + 1), pData, dataLen);
}


// NRFX_TWI_FLAG_NO_XFER_EVT_HANDLER
nrfx_err_t twi_data_write(uint8_t slaveAddr, uint8_t regAddr, uint8_t *pData, uint8_t dataLen, uint8_t device)
{
  // 这里的datalen 是 pData 的datalen ,一般取1 ，单字节的写入寄存器
    nrfx_err_t errCode = NRFX_SUCCESS;
    mergeRegisterAndData(twimWriteDataBuffer, regAddr, pData, dataLen);
    i2c_write(lc_twim, twimWriteDataBuffer, dataLen + 1, slaveAddr);
    return errCode;
}

nrfx_err_t twi_data_read(uint8_t slaveAddr, uint8_t regAddr, uint8_t *pData, uint8_t dataLen, uint8_t device)
{
  // 读取数据的过程为： 先write 一个 reg ，之后再读取data ,其中的pData 为接收数据的buffer 指针 ,dataLen为接收data的长度
    nrfx_err_t errCode = NRFX_SUCCESS;
    uint8_t regbuffer = regAddr;
    i2c_write(lc_twim, &regbuffer, sizeof(regbuffer), slaveAddr);
    i2c_read(lc_twim, pData, dataLen, slaveAddr);

    return errCode;
}


/**
 * @brief Function for handling TWIM driver events.
 *
 * @param[in] p_event Event information structure.
 */
// void lsm_twim_handler(nrfx_twim_evt_t const * p_event, void * p_context)
// {

// }

void lc_twim_handler(nrfx_twim_evt_t const * p_event, void * p_context)
{

}
/**
 * @brief init function of twim
 */
nrfx_err_t twim_init (void)
{
    nrfx_err_t err_code;
    // 注意：twim 可以直接使用 device tree 进行配置
    // nrfx_twim_config_t twim_config = NRFX_TWIM_DEFAULT_CONFIG(LSM_SCL_PIN ,LSM_SDA_PIN);
    // twim_config .frequency          = NRF_TWIM_FREQ_100K; // internal pull-up is too weak, only for 100kHz or lower  
    // twim_config .interrupt_priority = 3;
    // twim_config.hold_bus_uninit = false;
    // nrfx_twim_uninit(&lsm_twim); // 注意：配置device tree 会相当于在初始化，所以如果配置设备树就可以不用再初始化，有一些外设zepher会提前完成初始化
    // err_code = nrfx_twim_init(&lsm_twim, &twim_config, NULL, NULL); // lsm_twim_handler
    // NRFX_ASSERT(err_code == NRFX_SUCCESS);

    // nrfx_twim_config_t twim_config1 = NRFX_TWIM_DEFAULT_CONFIG(LC_SCL_PIN ,LC_SDA_PIN);
    // twim_config1 .frequency          = TWI_FREQUENCY_FREQUENCY_K400;
    // twim_config1 .interrupt_priority = 4;
    // twim_config1.hold_bus_uninit = false;
    
    // err_code = nrfx_twim_init(&lc_twim, &twim_config1, lc_twim_handler, NULL);
    // NRFX_ASSERT(err_code == NRFX_SUCCESS);

    // IRQ_CONNECT(NRFX_IRQ_NUMBER_GET(NRF_TWIM_INST_GET(LSM_INSTANCE_ID)), IRQ_PRIO_LOWEST,
    //          NRFX_TWIM_INST_HANDLER_GET(LSM_INSTANCE_ID), 0, 0);

    // nrfx_twim_enable(&lsm_twim);
    // nrfx_twim_enable(&lc_twim); 
    err_code = NRFX_SUCCESS;
    return err_code;
}

/*******************for lsm spi********************/
nrfx_err_t lsm_spim_init(void){
    // spi init
    // nrfx_spim_uninit(&lsm_spi);
    nrfx_err_t err;
    
    nrfx_spim_config_t lsm_spi_init = NRFX_SPIM_DEFAULT_CONFIG(LSM_SCL_PIN, LSM_SDI_PIN, LSM_SDO_PIN, LSM_CS_PIN);
    // lsm_spi_init.frequency = NRFX_MHZ_TO_HZ(8); 
    lsm_spi_init.bit_order = NRF_SPIM_BIT_ORDER_MSB_FIRST;
    lsm_spi_init.mode = NRF_SPIM_MODE_3; // < SCK active low, sample on trailing edge of clock.
    lsm_spi_init.orc = 0x00;

    err = nrfx_spim_init(&lsm_spi, &lsm_spi_init, NULL, NULL); // disable spi interruption
    if (err != NRFX_SUCCESS)
    {
      return err;
    }
    return 0;
}

nrfx_err_t data_write(uint8_t regAddr, uint8_t *pData, uint8_t dataLen, uint8_t device)
{
  // 这里的datalen 是 pData 的datalen ,一般取1 ，单字节的写入寄存器
    nrfx_err_t errCode = NRFX_SUCCESS;
    uint8_t temp_addr = regAddr;
    temp_addr = temp_addr & 0b01111111;
    mergeRegisterAndData(twimWriteDataBuffer, regAddr, pData, dataLen);
    nrfx_spim_xfer_desc_t xfer_desc = NRFX_SPIM_XFER_TX(twimWriteDataBuffer, dataLen + 1);
	  nrfx_spim_xfer(&lsm_spi, &xfer_desc, 0); 

    return errCode;
}

nrfx_err_t data_read(uint8_t regAddr, uint8_t *pData, uint8_t dataLen, uint8_t device)
{
    uint8_t rx_temp[dataLen + 1];
    uint8_t regbuffer = regAddr | 0x80; // RW value
  // 读取数据的过程为： 先write 一个 reg ，之后再读取data ,其中的pData 为接收数据的buffer 指针 ,dataLen为接收data的长度
    nrfx_err_t errCode = NRFX_SUCCESS;

    nrfx_spim_xfer_desc_t xfer_desc = NRFX_SPIM_XFER_TRX(&regbuffer, 1, rx_temp, dataLen + 1); //注意这里多读了一个字节的无效值要去掉
	  nrfx_spim_xfer(&lsm_spi, &xfer_desc, 0);

    memcpy(pData, (rx_temp + 1), dataLen);

    return errCode;
}
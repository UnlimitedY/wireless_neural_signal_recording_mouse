
/* 05/01/2021 Copyright Tlera Corporation
 *  
 *  Created by Kris Winer
 *  
 *  The LC709204F is a low-cost, low-power 1S LiPo battery fuel gauge.
 *  
 *  Library may be used freely and without limit with attribution.
 *  
 */
 
#include "LC709204F.h"

// LC709204F::LC709204F(I2Cdev* i2c_bus)
// {
//   _i2c_bus = i2c_bus;
// }


void getChipID(uint16_t *databuf)
{
    nrfx_err_t err;
    uint8_t userid[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_NUMBER_PARAM ,userid ,2, 0); // read number of the parameter, should be 0x1001
    if(err){
        //
    }
    *databuf = (userid[1] << 8) | userid[0];
}


void LC_init()
{
    uint8_t data[16] = {0x18 ,0x18 ,
                       0x00 ,0x00 ,
                       0x00 ,0x00 ,
                       0x00 ,0xA0 ,
                       0x0E ,0x10 ,
                       0x0C ,0x3C ,
                       0x00 ,0x01 ,
                       0x00 ,0x00};
    twi_data_write(LC709204F_ADDRESS, LC709204F_APA, &data[0] ,2, 0);                 // set APA for 100 mAH capacity
    twi_data_write(LC709204F_ADDRESS, LC709204F_CHANGE_PARAM,  &data[2] ,2, 0);       // set change of parameter for 3.7 V 1S LiPo
    twi_data_write(LC709204F_ADDRESS, LC709204F_STATUS_BIT,    &data[4] ,2, 0);       // set to I2C mode

    // Set up interrupts
    twi_data_write(LC709204F_ADDRESS, LC709204F_ALARM_LOW_RSOC,  &data[6] ,2, 0);     // set to alarm when RSOC falls below 10%
    //0x0E10 = 3600
    twi_data_write(LC709204F_ADDRESS, LC709204F_ALARM_LOW_CELL_VLT,  &data[8] ,2, 0); // set to alarm when battery voltage falls below 3.6 V
    //0x0C3C = 3132 = 2732 + 400 so alarms at 40 C
    twi_data_write(LC709204F_ADDRESS, LC709204F_ALARM_HIGH_TEMP,  &data[10] ,2, 0);    // set to alarm when temperature rises above 40 C

    // Set power mode and clear battery status
    twi_data_write(LC709204F_ADDRESS, LC709204F_IC_POWERMODE,  &data[12] ,2, 0);       // set to operate mode
    twi_data_write(LC709204F_ADDRESS, LC709204F_BATTERY_STATUS,  &data[14] ,2, 0);     // reset battery status
}


void LC_sleep()
{
    uint8_t data[2] = {0x00 ,0x02};
    twi_data_write(LC709204F_ADDRESS, LC709204F_IC_POWERMODE, data ,2, 0);      // set to sleep mode
}


void LC_operate()
{
    uint8_t data[2] = {0x00 ,0x01};
    twi_data_write(LC709204F_ADDRESS, LC709204F_IC_POWERMODE,  data ,2, 0);       // set to operate mode
}


void LC_getCellVoltage(uint16_t *databuf)
{
    // 
    nrfx_err_t err;
    uint8_t volt[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_CELL_VOLTAGE ,volt ,2, 0);
    *databuf = (volt[1] << 8) | volt[0];
  
}


void LC_getRSOC(uint16_t *databuf)
{
    nrfx_err_t err;
    uint8_t rsoc[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_RSOC ,rsoc ,2, 0);
    *databuf = (rsoc[1] << 8) | rsoc[0];
}


void LC_getITE(uint16_t *databuf)
{
    nrfx_err_t err;
    uint8_t ite[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_ITE ,ite ,2, 0);
    *databuf = (ite[1] << 8) | ite[0];
}


void LC_getStatus(uint16_t *databuf)
{
    nrfx_err_t err;
    uint8_t stat[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_BATTERY_STATUS ,stat ,2, 0);
    *databuf = (stat[1] << 8) | stat[0];
}


void LC_clearStatus()
{
    uint8_t data[2] = {0x00 ,0x00};
    twi_data_write(LC709204F_ADDRESS, LC709204F_BATTERY_STATUS,  data ,2, 0);     // reset battery status
}


void LC_timetoEmpty(uint16_t *databuf)
{
    nrfx_err_t err;
    uint8_t time[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_TIME_TO_EMPTY ,time ,2, 0);
    *databuf = (time[1] << 8) | time[0];
}


void LC_stateofHealth(uint16_t *databuf)
{
    nrfx_err_t err;
    uint8_t health[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_STATE_OF_HEALTH ,health ,2, 0);
    *databuf = (health[1] << 8) | health[0];
}


void LC_setTemperature(uint16_t temperature)
{
    uint8_t data[2] = {(uint8_t)(temperature >> 8) ,(uint8_t)(temperature)};
    twi_data_write(LC709204F_ADDRESS, LC709204F_CELL_TEMP, data ,2, 0); // input cell (MCU) temperature in 0.1 K
}


void LC_getTemperature(uint16_t *databuf)
{
    nrfx_err_t err;
    uint8_t cell[2];
    err = twi_data_read(LC709204F_ADDRESS, LC709204F_CELL_TEMP ,cell ,2, 0);
    *databuf = (cell[1] << 8) | cell[0];
}
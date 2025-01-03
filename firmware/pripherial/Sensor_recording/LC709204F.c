
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

int getChipID(void) // return 30
{
    uint16_t number_parame = 5;
    nrfx_err_t err;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_APT, &number_parame);
    return number_parame;
}

void LC_init()
{
    uint16_t data[8] = {0x1313 , // battery type-01: Nominal voltage:3.7V' charging voltage: 4.2V
                       0x0000 ,
                       0x0000 ,
                       0x00A0 ,
                       0x0E10 ,
                       0x0C3C ,
                       0x0001 ,
                       0x0000};
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_APA, data[0]);                 // set APA for 50 mAH capacity
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_CHANGE_PARAM,  data[1]);       // set change of parameter for 3.7 V 1S LiPo : Type -01
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_STATUS_BIT,    data[2]);       // 

    // // Set up interrupts
        // LC_twi_data_write(LC709204F_ADDRESS, LC709204F_ALARM_LOW_RSOC,  data[3]);     // set to alarm when RSOC falls below 10%
        // //0x0E10 = 3600
        // LC_twi_data_write(LC709204F_ADDRESS, LC709204F_ALARM_LOW_CELL_VLT,  data[4]); // set to alarm when battery voltage falls below 3.6 V
        // //0x0C3C = 3132 = 2732 + 400 so alarms at 40 C
        // LC_twi_data_write(LC709204F_ADDRESS, LC709204F_ALARM_HIGH_TEMP,  data[5]);    // set to alarm when temperature rises above 40 C

    // Set power mode and clear battery status
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_IC_POWERMODE,  data[6]);       // set to operate mode
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_BATTERY_STATUS,  data[7]);     // reset battery status for some flags indicating spectial events
}


void LC_sleep()
{
    uint16_t data = 0x0002;
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_IC_POWERMODE, data);      // set to sleep mode
}


void LC_operate()
{
    uint16_t data = 0x0001;
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_IC_POWERMODE,  data);       // set to operate mode
}


void LC_getCellVoltage(uint16_t *databuf)
{
    // 
    nrfx_err_t err;
    uint16_t volt;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_CELL_VOLTAGE ,&volt);
    *databuf = volt;
  
}

void LC_getRSOC(uint16_t *databuf)
{
    nrfx_err_t err;
    uint16_t rsoc;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_RSOC ,&rsoc);
    *databuf = rsoc;
}


void LC_getITE(uint16_t *databuf)
{
    nrfx_err_t err;
    uint16_t ite;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_ITE ,&ite);
    *databuf = ite;
}


void LC_getStatus(uint16_t *databuf)
{
    nrfx_err_t err;
    uint16_t stat;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_BATTERY_STATUS ,&stat);
    *databuf = stat;
}





void LC_clearStatus()
{
    uint16_t data = 0x0000;
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_BATTERY_STATUS,  data);     // reset battery status
}


void LC_timetoEmpty(uint16_t *databuf)
{
    nrfx_err_t err;
    uint16_t time;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_TIME_TO_EMPTY ,&time);
    *databuf = time;
}


void LC_stateofHealth(uint16_t *databuf)
{
    nrfx_err_t err;
    uint16_t health;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_STATE_OF_HEALTH ,&health);
    *databuf = health;
}


void LC_setTemperature(uint16_t temperature)
{
    LC_twi_data_write(LC709204F_ADDRESS, LC709204F_CELL_TEMP, temperature); // input cell (MCU) temperature in 0.1 K
}


void LC_getTemperature(uint16_t *databuf)
{
    nrfx_err_t err;
    uint16_t cell;
    err = LC_twi_data_read(LC709204F_ADDRESS, LC709204F_CELL_TEMP ,&cell);
    *databuf = cell;
}
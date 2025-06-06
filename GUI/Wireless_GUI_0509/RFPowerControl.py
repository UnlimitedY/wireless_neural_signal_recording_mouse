# -*- coding: utf-8 -*-
import serial
import binascii
import string
import time
#打开串口


class serialPowerControl():
    def __init__(self):
        self.serialPort = "COM23"  # 串口
        self.baudRate = 9600  # 波特率
        self.s = serial.Serial(self.serialPort, self.baudRate, timeout=0.5)
        self.status = 0 
    def open(self):
        d=bytes.fromhex('A0 01 03 A4')
        self.s.write(d)
        print("打开继电器！！！！！！！！")
        time.sleep(0.1)
        n = self.s.inWaiting()
        self.status = str(binascii.b2a_hex(self.s.read(n)))[2:-1]
    def close(self):
        d = bytes.fromhex('A0 01 02 A3')
        self.s.write(d)
        print("关闭继电器！！！！！！！！")
        time.sleep(0.1)
        n = self.s.inWaiting()
        self.status = str(binascii.b2a_hex(self.s.read(n)))[-2] # open: 2; close: 1
    def read_status(self):
        d = bytes.fromhex('A0 01 05 A6')
        self.s.write(d)
        time.sleep(0.1)
        n = self.s.inWaiting()
        self.status = str(binascii.b2a_hex(self.s.read(n)))[-2] # open: 2; close: 1
   

#收发数据
#n = s.inWaiting()
#if n:
#  data = str(binascii.b2a_hex(s.read(n)))[2:-1]
#  print(data)
#通讯协议
#指令通过16进制形式发送
#数据（1）---启始标识（默认为0xA0）
#数据（2）---开关地址码（默认为0x01，标识第1路；0x02标识第2路…依次类推）
#数据（3）---操作数据（0x00为关不反馈，0x01为开不反馈，0x02为关并反馈，0x03为开并反馈，0x04为取反并反馈，0x05为查询状态0X06为闪断并反馈）
#数据（4）---校验码（前面三个数据加和）

#示例
#打开第1路USB开关不反馈：A0 01 01 A2，继电器会吸合，但不会反馈数据
#关闭第1路USB开关不反馈：A0 01 00 A1，继电器会释放，但不会反馈数据

#打开第1路USB开关并反馈：A0 01 03 A4，继电器会吸合，并反馈状态A0 01 01 A2
#关闭第1路USB开关并反馈：A0 01 02 A3，继电器会释放，并反馈状态A0 01 00 A1

#取反第1路USB开关并反馈：A0 01 04 A5，继电器的状态会变化，并反馈最终状态
#关闭第1路USB开关不反馈：A0 01 05 A6，继电器会反馈实时状态
#打开第2路USB开关不反馈：A0 02 01 A3，继电器会吸合，但不会反馈数据
#关闭第2路USB开关不反馈：A0 02 00 A2，继电器会释放，但不会反馈数据
#打开第3路USB开关不反馈：A0 03 01 A4，继电器会吸合，但不会反馈数据
#关闭第3路USB开关不反馈：A0 03 00 A3，继电器会释放，但不会反馈数据
#打开第4路USB开关不反馈：A0 04 01 A5，继电器会吸合，但不会反馈数据
#关闭第4路USB开关不反馈：A0 04 00 A4，继电器会释放，但不会反馈数据
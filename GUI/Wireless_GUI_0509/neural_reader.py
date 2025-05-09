# 这个脚本用来对收到的数据进行处理(包括ad 转换为float的数据类型)，返回并处理错误的数据：需要的数据格式为：
# 关于数据保存：n is data dims;每过100 * 10000 sample point（包括丢失的data）~ 51s 记录一个文件，该文件有两行；其中一行为1*n 记录所有的raw data， 另一行为electrode 记录所有sample point对应的电极channel
#                     每次暂停都重新记录一个文件，并获取新的timestamp来计算 自增timestamp;其中 raw data的值用u16来表示raw value             
#               对于spike 数据，同上，使用同一的文件命名；记录的格式为uint8，有16行 ，每行都是一个channel ，一行数据量为5 * 10000

# update_raw_data : 1 * 120 * 1600 (~ 10s ),每次update都等1s左右的数据读取到了就告诉gui去读取更新一次；读满之后覆盖掉原来的数据;
# spike_timestamp: 16 * 6 * 1600 处理同上

""" 
直接记录所有能记录到的数据;记录满一定数量就保存为一个文件;通过timestamp来确定包的时刻;丢包的情况也通过timestamp来确定;
"""
from asyncore import read
from email import message
import asyncio
from aioserial import AioSerial
import serial
import time
import threading
import binascii
import numpy as np
import json
import datetime
from multiprocessing import Process, freeze_support

import collections as coll
from PyQt6.QtCore import QThread, pyqtSignal, QObject

import re

def get_raw_data_container(): # LFP raw data TODO HABITS events
    raw_data = {  # maximum 16 channels
        "Channel_0":[],
        "Channel_1":[],
        "Channel_2":[], 
        "Channel_3":[],
        "Channel_4":[], 
        "Channel_5":[],
        "Channel_6":[],
        "Channel_7":[],
        "Channel_8":[], 
        "Channel_9":[],
        "Channel_10":[],
        "Channel_11":[],
        "Channel_12":[],
        "Channel_13":[],
        "Channel_14":[],
        "Channel_15":[],

        "TimeStamp":[] , # basic unit is packet

        "MissPackets":0,
        "MissPacketsIndex":[]
        } 
    return raw_data

def get_events_data_container(): # Action potiential events & other recorded data
    events_data =  {
        "AcclX":[],
        "AcclY":[],
        "AcclZ":[],
        "GryoX":[],
        "GryoY":[],
        "GryoZ":[],

        "RSOC":[],
        "BatteryStatus":[],
        "BatteryTemp":[]
        } 
    return events_data

def spike_data_container(): # mode 1; raster 16 channels + 1 channel raw data
    spike_data = {
        "AP_timestamp":[] , # raw data
        "Electrode":[] ,
        "Raw_data":[],
        "Raw_channel":[],
        "Raw_timestamp":[],
        "SpikeThreshold":[],

        "HABITS_event_1":[],

        "MissPackets":0,
        "MissPacketsIndex":[]
    }
    return spike_data


def swap16Hex(str):
    return str[2:4] + str[0:2]


def my_gaussian_filter1d(seq, sigma=50 ,truncate=4.0 ,order=0): 
    """allow NaN elements
    sigma: 50 windows 401
    seq's type is ndarray
    """
    if seq.ndim > 1:
        seq = np.squeeze(seq ,1)
    length = len(seq)
    ## prepare Kernel
    sd = float(sigma)
    # make the radius of the filter equal to truncate standard deviations
    lw = int(truncate * sd + 0.5) # radius 
    weights = gaussian_kernel1d(sigma, order, lw)
    #print("weights_length:" ,weights.shape[0])
    ## NaN padding
    pad = lw 
    out = np.zeros((length + pad * 2), dtype=np.float64) # 1 dim
    out[pad: pad + length] = seq.copy().astype(np.float64)
    out[0:pad] = np.nan
    out[-pad:] = np.nan
    tmp = out.copy()
    ## filtering
    for y in range(length):
        mask = np.where(np.isnan(tmp[y: y + len(weights)]) == False) # 选择不是nan的部分,并返回对应的index值
        if np.size(mask) != 0:
            out[pad + y] = np.sum(weights[mask] * tmp[y: y + len(weights)][mask]) / np.sum(weights[mask]) #TODO 再检查一下
        else:
            out[pad + y] = np.nan
    #out = np.clip(out, 0, 1) # 对于有nan值不适用
    out = out[pad:pad + length]
    return out

def gaussian_kernel1d(sigma, order, radius):
    """
    Computes a 1-D Gaussian convolution kernel.
    """
    if order < 0:
        raise ValueError('order must be non-negative')
    exponent_range = np.arange(order + 1)
    sigma2 = sigma * sigma
    x = np.arange(-radius, radius+1)
    phi_x = np.exp(-0.5 / sigma2 * x ** 2)
    phi_x = phi_x / phi_x.sum()

    if order == 0:
        return phi_x
    else:
        q[0] = 1
        D = np.diag(exponent_range[1:], 1)  # D @ q(x) = q'(x)
        P = np.diag(np.ones(order)/-sigma2, -1)  # P @ q(x) = q(x) * p'(x)
        Q_deriv = D + P
        for _ in range(order):
            q = Q_deriv.dot(q)
        q = (x[:, None] ** exponent_range).dot(q)
        return q * phi_x

# filter
def LFP_filter(data, low_cutoff="None", high_cutoff="None", fs=1000, order=4): #TODO 容易溢出
    """
    对神经信号进行带通、低通或高通滤波
    
    参数:
    data: numpy数组，输入的神经信号数据
    low_cutoff: 低截止频率（Hz），如果为None则执行低通滤波
    high_cutoff: 高截止频率（Hz），如果为None则执行高通滤波
    fs: 采样频率（Hz），默认为1000Hz
    order: 滤波器阶数，默认为4
    
    返回:
    filtered_data: 滤波后的数据，与输入数据维度相同
    """
    from scipy.signal import butter, filtfilt
    import numpy as np
    
    # 检查输入数据类型
    if not isinstance(data, np.ndarray):
        data = np.array(data)
    
    # 保存原始数据形状
    original_shape = data.shape
    
    # 将数据转换为一维数组进行处理
    data_1d = data.flatten()

    # 根据提供的截止频率确定滤波器类型
    if low_cutoff != "None" and high_cutoff != "None":
        low_cutoff = float(low_cutoff)
        high_cutoff = float(high_cutoff)
        # 带通滤波
        nyq = 0.5 * fs
        low = low_cutoff / nyq
        high = high_cutoff / nyq
        b, a = butter(order, [low, high], btype='band')
    elif low_cutoff != "None":
        low_cutoff = float(low_cutoff)
        # 高通滤波
        nyq = 0.5 * fs
        cutoff = low_cutoff / nyq
        b, a = butter(order, cutoff, btype='high')
    elif high_cutoff != "None":
        high_cutoff = float(high_cutoff)
        # 低通滤波
        nyq = 0.5 * fs
        cutoff = high_cutoff / nyq
        b, a = butter(order, cutoff, btype='low')
    else:
        # 如果没有提供截止频率，则返回原始数据
        return data
    
    # 应用滤波器
    filtered_data = filtfilt(b, a, data_1d)
    
    # 将滤波后的数据恢复为原始形状
    filtered_data = filtered_data.reshape(original_shape)
    # print(filtered_data)
    
    return filtered_data

""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
class SerialPort(QThread):
    GUIUpdate = pyqtSignal(list)

    def __init__(self ,port ,buand) -> None:
        super(SerialPort ,self).__init__()

        """ for test """
        self.test = 0
        self.test1 = []
        self.test2 = 0
        self.tiema = 0
        """ GUI system """
        # alignment
        self.alignment_timestamp = time.time() # 每次开始进行sample 时记录的开始的绝对timestamp(下位机开机以来经过的ms时间)

        self.GUIUpdateInterval = 10 # 单位为packets num , per 40 packets upadte the GUI graphs ;2000 packets one file
        self.UpdateCounter = 0

        # double buffer GUI 
        self.doubleBuffer = 0
        # lfp
        self.lfptimestamp_GUI = []
        self.lfpdata_GUI = [[] for _ in range(16)]
        # sensor
        self.sensordata_GUI = [[] for _ in range(9)]
        # spike mode 1
        self.spiketimestamp_GUI = []
        self.spikedata_GUI = [] # only 1 channel
        self.spikerasterdata_GUI = [[] for _ in range(16)] 
        # spike mode 2
        self.spiketimestamp_mode2_GUI = []
        self.spikechannel_mode2_GUI = []
        self.spikedata_mode2_GUI = [[] for _ in range(16)] # 16 channel with 4 active channels

        # for test
        self.receive_num_packet = 0
        self.overflow = 0
        self.qq = 0

        """ Data stream """
        self.rssi = 0 # real-time rssi
        self.rf_channel = 0 # current rf channel
        self.rf_channel_rssi = 0 # noise rssi
        self.USBFIFO = coll.deque(maxlen=1000)
        self.lfp_data_buffer = ''
        self.lfp_timestamp_buffer = []
        self.lfp_buffer_counter = 0
        self.lfp_maxlen = 1
        self.LFPRawCounter = 0

        self.port = serial.Serial(port ,buand)
        self.port.close() # close the port to avoid the error at the begining of Serial initalization

        """ packages processing """
        self.message = '' 
        self.packetID = -1 # 用来判断收到的packet的类型，并分别对不同的packet进行拆包处理
        self.packet_counter = 0 # 在数据传输过程中记录到的packet 的offset: timestamp
        self.DAC_resolution = 1/(int('ffff' ,16)) * 1.225 * 2 # 1.225 is the reference voltage of the series of RHD2000 (bipolar ADC)

        """ real-time long-term LFP or spike raw data recording mode 0"""
        self.raw_data_per_packet_channel = 7
        self.raw_data_per_packet = self.raw_data_per_packet_channel * 16
        self.raw_data_index_base = None
        self.sensor_index = None
        
        """ Event-triggered Spike raw data & AP recording """
        # mode 1
        self.spike_channel_index_mode1 = 16 # mode 1
        self.SPIKERawCounter = 0
        self.spike_data_buffer = ''
        self.spike_timestamp_buffer = []
        self.spike_buffer_counter = 0
        self.spike_maxlen = 1
        # mode 2
        self.spike_FIFO_mode2 = coll.deque(maxlen=1000)
        self.spike_raw_channel = [0, 1, 2, 3] # 记录当前记录spike的raw channel; mode 2
        self.SPIKEsensorCounter_mode2 = 0
        self.SPIKERawCounter_mode2 = 0
        self.spike_losspackets_mode2 = 0

        # remove duplicate packets and sorting acoording to timestamp and packets_index
        self.spike_maxlen_mode2 = 10
        self.spike_buffer_counter_mode2 = 0
        
        """ spike detection """
        self.calcST = []
        
        """ Logging """
        self.sample_times = 0 # 记录 sample 开始的次数；也就是暂停sample 的次数
        
        """ File saving """
        self.lfp_file_addr = ''
        self.save_file_lfp_flag = False
        # LFP raw data or spike raw data
        self.raw_data = get_raw_data_container()
        # Action potiential events & other recorded data
        self.sensors_data = get_events_data_container()
        # Action potiential events data
        self.AP_data = spike_data_container()
        
        self.file_size = 5000 # packets; default: equal to self.GUIUpdateInterval; in 1khz LFP: it's 12s；# 这个值不能设置太大，否则会导致缓存问题
        
        self.overflowSignal = [0, 0] # last and current

        self.LFP_max_interval = 8 # the maximum interval between raw data packets: 2khz lfp: 4; 1khz: 8
        self.Spike_max_interval = 6 # same as above but for the minimum value

        """ IMU & LC data recording """
        self.sensor_update_flag = 0
        self.sensor_name = list(self.sensors_data.keys())
        self.batteryStatus = 0

    def port_open(self):
        """ seiral ports opening """
        #### read parameters
        if not self.port.isOpen():
            self.port.open()
    
    def port_close(self):
        """ serial ports closing """
        self.port.close()
    
    def send_data(self ,data):
        """ write commands to peripheral """
        n = self.port.write(data) # must is bytes
        return n
    
    def load_parameters(self):
        with open('.\Reader_params.json', 'r') as file:
            data = json.load(file)
            self.alignment_timestamp = data["timestamp_ms"]
        pass

    def read_data(self):
        """ read fifo of usbd """
        # # 清除 uart 的buffer
        self.flush()
        # get the raw_data_index_base
        self.get_decoding_index()
        full_frame = bytearray()

        self.tiema = time.time_ns()
        while(True): # async main loop
            # read neural data containing n packets    
            # read decoded by acsii ,and the type is str ,the expected str is the stop signal; 50ms->20 packets
            # 这个命令会导致阻塞(等待usb上传data的速度，最好搭配异步处理)，同时效率低下（需要循环读取单字节来判断until事件） 最好serial都使用read_all()
            # self.USBFIFO.append(self.port.read_until(b'%&\'(')) 
            # self.data_process_full()

            temp_frame = self.port.read_all()
            if(len(temp_frame) == 0):
                continue
            full_frame += bytearray(temp_frame)
            if(full_frame[-4:] != b'%&\'('):
                continue
            else:
                self.USBFIFO.append(full_frame)
                full_frame = bytearray()
                self.data_process_full()
                
            
    def data_process_full(self):
        # GUI updater
        self.GUIUpate_enable()
        read_data = self.USBFIFO.popleft()
        if(len(read_data)!= 0):
            read_data = str(binascii.b2a_hex(read_data ,' ', 2))
            spilt_temp = re.split('[ ][2][1][2][2][ ][2][3][2][4][ ]',read_data[2:-10])[0:-1] # 注意，这个正则化表达式很重要
            
            """ 6 kinds of packets:
            1. raw data: include LFP/Spike raw data + IMU + LC + spike events
            2. timestamp: the onset of sampling
            3. empty: when the sample is stopping
            """
            for _, packets in enumerate(spilt_temp):
                # print(packets)
                self.receive_num_packet += 1
                # get the category of packets
                try:
                    packets_type = int(packets[2:4], 16)
                    # rssi value occupy one short
                    self.rssi = round(int(packets[-4:-2], 16) * 0.01 + self.rssi * 0.99 , 2)
                    packets = packets[0:-5]
                    packet_length = (len(packets) + 1) / 5 
                except:
                    packets_type = -1
                    packet_length = 0
                    pass

                # packet proprocessing 
                """ lfp packets: mode 0 """
                if(packets_type == 1 and packet_length == 125): #  lfp packets: mode 0
                    self.LFPRawCounter += 1
                    # self.UpdateCounter += 1
                    # get timestamp + lfp channel length + overflow signal
                    lfp_timestamp_temp = self.timestamp_calibration(int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16))
                    self.lfp_timestamp_buffer.append(lfp_timestamp_temp + self.alignment_timestamp) # timestamp
                    _ = int(packets[0:2] ,16) # channel num of each packets
                    self.overflowSignal[1] = int(packets[15:17] ,16) # current signal
                    self.sensor_update_flag = int(packets[17:19] ,16) # sensor signal
                    
                    # lfp packets: 10 packets process
                    self.lfp_data_buffer += (packets[20:] + ' ')
                    self.lfp_buffer_counter += 1
           
                    ## only proprocess sensor data + lfp raw data
                    if(self.lfp_buffer_counter >= self.lfp_maxlen):
                        self.lfp_packets_process()
                        self.lfp_buffer_counter = 0
                        self.lfp_timestamp_buffer = []
                        self.lfp_data_buffer = ''
                    # file saving
                    if(self.save_file_lfp_flag):
                        self.save_lfp_file(self.lfp_file_addr)

                    """  spike packets: mode 1 """
                elif(packets_type == 2 and packet_length == 108): 
                    self.SPIKERawCounter += 1
                    spike_timestamp_mode1_temp = self.timestamp_calibration(int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16))
                    
                    # print(int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16) - self.qq)
                    self.qq = int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16)
                    self.spike_timestamp_buffer.append(spike_timestamp_mode1_temp) # timestamp
                    self.spike_channel_index_mode1 = int(packets[0:2] ,16) # channel index of current packets
                    self.overflowSignal[1] = int(packets[15:17] ,16) # current signal
                    self.sensor_update_flag = int(packets[17:19] ,16) # sensor signal

                    self.spike_data_buffer += (packets[20:] + ' ')
                    self.spike_buffer_counter += 1

                    if(self.spike_buffer_counter >= self.spike_maxlen):
                        self.spike_packets_process()
                        self.spike_buffer_counter = 0
                        self.spike_timestamp_buffer = []
                        self.spike_data_buffer = ''

                    self.save_spike_mode1_file()
                    pass
                
                    """  spike packets: mode 2 """
                elif(packets_type == 6 and packet_length == 13): # other sensor data: 1 packets every 6ms
                    self.SPIKEsensorCounter_mode2 += 1
                    _ = self.timestamp_calibration(int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16)) # timestamp
                    self.overflowSignal[1] = int(packets[15:17] ,16) # current signal
                    self.sensor_update_flag = int(packets[17:19] ,16) # sensor signal

                    self.spike_sensor_packets_process_mode2(packets[20:] + ' ') 

                    pass
                    
                elif(packets_type == 5 and packet_length == 126): # spike raw data with lfp: 3 packets every 6ms
                    """ 注意，这里需要做一下包的排序，包之间的间隔过短 会出现包顺序的错乱和重复: TODO"""
                    self.spike_buffer_counter_mode2 += 1
                    # timestamp
                    temp_timestamp_mode2 = self.timestamp_calibration(int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16))
                    # current index 
                    temp_packet_index = int(packets[0:2] ,16) # index of 3 packets list
                    # current signal
                    self.overflowSignal[1] = int(packets[15:17] ,16) 
                    # current recording channels
                    self.spike_raw_channel[0] = int(packets[22:24] ,16)
                    self.spike_raw_channel[1] = int(packets[20:22] ,16)
                    self.spike_raw_channel[2] = int(packets[27:29] ,16)
                    self.spike_raw_channel[3] = int(packets[25:27] ,16)

                    # for test: check the send rate
                    tiemb = time.time_ns()
                    if(tiemb - self.tiema >= 1000 * 1000 * 1000 * 60): # 60s
                        print("losspackets_per_sample", self.spike_losspackets_mode2/self.spike_buffer_counter_mode2, 252 * self.spike_buffer_counter_mode2 / 1000 / 60 * (120/126), "kB/s", 
                              "error order:", self.test2/self.spike_buffer_counter_mode2) # kB/s
                        # reinit param
                        self.spike_buffer_counter_mode2 = 0
                        self.spike_losspackets_mode2 = 0
                        self.tiema = time.time_ns()
                        self.test2 = 0
                    if((temp_timestamp_mode2 - self.test < 0)):
                        self.test2 += 1
                    self.test = temp_timestamp_mode2

                    self.spike_FIFO_mode2.append([temp_timestamp_mode2, temp_packet_index, self.spike_raw_channel, (packets[30:] + ' ')]) # timestamp + packet_index + channel_index + raw data
                    
                    # process data
                    self.spike_raw_packets_process_mode2()
                    pass

                    """ for timestamp alignment """
                elif(packets_type == 4): # empty payload
                    # print("Sdvsdfv")
                    pass
                elif(packets_type == 3): # timestamp payload
                    current_time = int(time.time() * 1000)
                    timestamp_message = np.array(packets.split(' ')) # 取所有个 short
                    
                    # rssi 
                    self.rf_channel =  int(swap16Hex(timestamp_message[5][0:2]) ,16)
                    self.rf_channel_rssi = int(swap16Hex(timestamp_message[5][2:4]) ,16)

                    timestamp_from_pri = ''
                    for bt in timestamp_message[1:5]:
                        timestamp_from_pri += (swap16Hex(bt))
                    timestamp_from_pri = int(timestamp_from_pri ,16)
                    # 基于函数的时间误差校正
                    self.alignment_timestamp = current_time - self.timestamp_calibration(timestamp_from_pri) # 实际的系统开机时间
                    
                    print("system on:", self.alignment_timestamp)
                    # save to file
                    with open('Reader_params.json', 'r') as f:
                        data = json.load(f)
                    data["timestamp_ms"] = self.alignment_timestamp
                    with open('Reader_params.json', 'w') as f:
                        json.dump(data, f, indent=2)    # 保持2个缩进
                    pass

          
    def spike_sensor_packets_process_mode2(self, sensor_data):
        # spilt
        temp_sensor_data = np.array(sensor_data.split(' '))[0:-1]
        # sensor data
        temp_sensor_data[0:3] = np.array(list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3])))
        temp_sensor_data[3:6] = np.array(list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6])))
        # LC data
        temp_sensor_data[6:] = np.array(list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:])))
        for i in range(9):
            temp_sensor = list(temp_sensor_data[np.arange(0 + i, len(temp_sensor_data) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # for file
            # self.sensors_data[self.sensor_name[i]].extend(temp_sensor)
            if(i == 7):
                # battery status
                if(0 in temp_sensor): # TODO other situations
                    self.batteryStatus = 0 # normal
        pass

    def spike_raw_packets_process_mode2(self):
        if(len(self.spike_FIFO_mode2) >= self.spike_maxlen_mode2):
            self.SPIKERawCounter_mode2 += 1 # for file saving

            index_temp = list(np.arange(0, self.spike_maxlen_mode2, 1))
            timestamp_temp = [] # 10
            packetIndex_temp = []
            FIFO_list_temp = []  # 看前10个包的数据
            # get pop times
            for i in range(self.spike_maxlen_mode2): 
                FIFO_temp = self.spike_FIFO_mode2.popleft()
                FIFO_list_temp.append(FIFO_temp)
                timestamp_temp.append(FIFO_temp[0])
                packetIndex_temp.append(FIFO_temp[1])

            ## sort acording to timestamp and packet index
            index_temp = sorted(index_temp, key=lambda x: (timestamp_temp[x], packetIndex_temp[x]))
            timestamp_temp = np.array(timestamp_temp)[index_temp]
            packetIndex_temp = np.array(packetIndex_temp)[index_temp]
            FIFO_list_temp = np.array(FIFO_list_temp, dtype=object)[index_temp]
            # remove duplicate value
            _, non_duplicate_index =np.unique(np.array([timestamp_temp, packetIndex_temp]),return_index=True, axis=1)
            FIFO_list_temp = FIFO_list_temp[non_duplicate_index]
            timestamp_temp = timestamp_temp[non_duplicate_index]
            packetIndex_temp = packetIndex_temp[non_duplicate_index]

            current_timestamp = np.unique(timestamp_temp)[0]
            temp_pop_times = np.sum(timestamp_temp == current_timestamp)

            for i in range(temp_pop_times): 
                temp_mode2 = FIFO_list_temp[i]
                # packet index and timestamp
                temp_i_timestamp = temp_mode2[0]
                temp_i_packetIndex = temp_mode2[1] # 0~2
                # spilt raw data
                temp_raw_mode2 = np.array(temp_mode2[3].split(' '))[0:-1]
                emp_channel_DAC = list(map(lambda x:self.DAC(x, raw=False), temp_raw_mode2))
                # raw data
                for i, channel_num in enumerate(temp_mode2[2]): # channel index: 4 channels : 30 points per packet per channel
                    self.spikedata_mode2_GUI[channel_num].extend(emp_channel_DAC[30 * i:30 * (i + 1)])
            
            # give to GUI buffer for timestamp
            self.spiketimestamp_mode2_GUI.append(current_timestamp) # timestamp

            # append back to fifo
            for i in range(len(non_duplicate_index) - temp_pop_times):
                self.spike_FIFO_mode2.appendleft(FIFO_list_temp[len(non_duplicate_index) - i - 1])

            if(temp_pop_times != 3):
                # print(temp_pop_times, timestamp_temp, packetIndex_temp)
                self.spike_losspackets_mode2 += (3 - temp_pop_times)
            # 3. save to file TODO
        pass

    def lfp_packets_process(self):
        # spilt
        self.lfp_data_buffer = np.array(self.lfp_data_buffer.split(' '))[0:-1]
       
        # 1. raw data 
        for channel_num in range(16):
            temp_channel = self.lfp_data_buffer[self.raw_data_index_base + channel_num * self.raw_data_per_packet_channel] # 注意这里要乘以7，每一个通道有7个连续的数据！！调了一整天这个bug 服了
            temp_channel_DAC = list(map(lambda x:self.DAC(x, raw=False), temp_channel))
            # print(temp_channel_DAC)
            # save to file
            self.raw_data["Channel_{}".format(channel_num)].extend(temp_channel_DAC)
            # give to GUI buffer
            self.lfpdata_GUI[channel_num].extend(temp_channel_DAC)
        
        # 2. timestamp
        self.raw_data["TimeStamp"].extend(self.lfp_timestamp_buffer)
        self.lfptimestamp_GUI.extend(self.lfp_timestamp_buffer)
            
        # 3. sensor data
        temp_sensor_data = self.lfp_data_buffer[self.sensor_index]
        # sensor data
        temp_sensor_data[0:3] = np.array(list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3])))
        temp_sensor_data[3:6] = np.array(list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6])))
        # LC data
        temp_sensor_data[6:] = np.array(list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:])))
        
        for i in range(9):
            temp_sensor = list(temp_sensor_data[np.arange(0 + i, len(temp_sensor_data) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # for file
            self.sensors_data[self.sensor_name[i]].extend(temp_sensor)
            if(i >= 6):
                # battery status
                # print(i, temp_sensor)
                if(0 in temp_sensor): # TODO other situations
                    self.batteryStatus = 0 # normal


    def spike_packets_process(self):
        # spilt
        self.spike_data_buffer = np.array(self.spike_data_buffer.split(' '))[0:-1]
        # 1. raw data + timestamp
        temp_channel = self.spike_data_buffer[13:-5] 
        temp_channel_DAC = list(map(lambda x:self.DAC(x, raw=False), temp_channel))

        # 2. give to GUI buffer
        self.spikedata_GUI.extend(temp_channel_DAC)
        self.spiketimestamp_GUI.extend(self.spike_timestamp_buffer)
        
        # 3. save to file
        # self.AP_data["Channel_{}".format(channel_num)].extend(temp_channel_DAC)
        # self.AP_data["TimeStamp"].extend(self.lfp_timestamp_buffer)
            
        # 4. sensor data
        temp_sensor_data = self.spike_data_buffer[self.sensor_index]
        # sensor data
        temp_sensor_data[0:3] = np.array(list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3])), dtype=np.float32)
        temp_sensor_data[3:6] = np.array(list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6])), dtype=np.float32)
        # LC data
        temp_sensor_data[6:] = np.array(list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:])), dtype=np.float32)
        for i in range(9):
            temp_sensor = list(temp_sensor_data[np.arange(0 + i, len(temp_sensor_data) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # for file
            # self.sensors_data[self.sensor_name[i]].extend(temp_sensor)
            if(i == 7):
                # battery status
                if(0 in temp_sensor): # TODO other situations
                    self.batteryStatus = 0 # normal
        
        # 5. raster data
        temp_raster_data = self.spike_data_buffer[-5:]
        for spike_data in temp_raster_data:
            spike_data = format(self.DAC(swap16Hex(spike_data)) ,'#018b')[2:] # 保留 前16位
            for channel_num ,spike_num in enumerate(spike_data):
                self.spikerasterdata_GUI[15 - channel_num].append(int(spike_num))


    def save_lfp_file(self, addr):
        """ save data to a file"""
        # the conditions of saving to a file:
        # 1. every stop events of sample
        # 2. per 2000 raw data packets
        if(self.LFPRawCounter == self.file_size or sum(self.overflowSignal) == 1):
            self.LFPRawCounter = 0
            # 1. detect if there exist one or mutiple miss packets when save raw data to a structured file
            timestamp_files = np.array(self.raw_data["TimeStamp"])
            timestamp_diff = np.diff(timestamp_files)
            
            # recording the missed packets number
            miss_packets = np.argwhere((timestamp_diff > self.LFP_max_interval) | (timestamp_diff <= 0)).flatten() # the interval exceed the set value
            self.raw_data["MissPacketsIndex"] = miss_packets
            # number
            miss_packets_num = np.ceil(timestamp_diff[miss_packets] / self.LFP_max_interval)
            miss_packets_num = np.sum(miss_packets_num.flatten())
            self.raw_data["MissPackets"] = miss_packets_num
            
            # 2. save the file
            """ load methods
            data = np.load("xxx.npy", allow_pickle=True)
            print(data.item()["TimeStamp"]) ...
            """
            now_time=datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
            # TODO 后续开启一个定时线程合并这些temp 文件 ；每n小时一个文件
            np.save(addr[0:-4] + str(now_time) + ".npy", self.raw_data, dict)
            np.save(addr[0:-4] + str(now_time) + ".npy", self.sensors_data , dict)
            
            # 3. reinit the temp array
            self.raw_data = get_raw_data_container()
            self.sensors_data = get_events_data_container()

            # 4. resample detection
            if(sum(self.overflowSignal) == 1): #  重新开始sample
                self.sample_times += 1
                self.overflowSignal[0] = self.overflowSignal[1]
                print("sample begin!")
            self.receive_num_packet = 0

    def save_spike_mode1_file(self):
        pass

    def GUIUpate_enable(self):
        # print(len(self.spiketimestamp_mode2_GUI))
        """ GUI update """ 
        if(len(self.lfptimestamp_GUI) >= self.GUIUpdateInterval):
            self.GUIUpdate.emit([[0], self.lfptimestamp_GUI, self.lfpdata_GUI, self.sensordata_GUI]) # mode 0
            self.lfptimestamp_GUI = []
            self.lfpdata_GUI = [[] for _ in range(16)]
            self.sensordata_GUI = [[] for _ in range(9)]
        elif(len(self.spiketimestamp_GUI) >= self.GUIUpdateInterval):
            self.GUIUpdate.emit([[1, self.spike_channel_index_mode1], self.spiketimestamp_GUI, self.spikedata_GUI, self.sensordata_GUI, self.spikerasterdata_GUI]) # mode 1
            self.spiketimestamp_GUI = []
            self.spikedata_GUI = []
            self.spikerasterdata_GUI = [[] for _ in range(16)]
            self.sensordata_GUI = [[] for _ in range(9)]
        elif(len(self.spiketimestamp_mode2_GUI) >= self.GUIUpdateInterval // 5): 
            self.GUIUpdate.emit([[2], self.spiketimestamp_mode2_GUI, self.spikedata_mode2_GUI, self.sensordata_GUI]) # mode 2
            self.spiketimestamp_mode2_GUI = []
            self.sensordata_GUI= [[] for _ in range(9)]
            self.spikedata_mode2_GUI = [[] for _ in range(16)]
      
          

    def get_decoding_index(self):
        """ lfp_ index """
        self.raw_data_index_base = np.array([])
        self.sensor_index = np.array([])
        temp_index = np.arange(0, self.lfp_maxlen * self.raw_data_per_packet, self.raw_data_per_packet)
        for i in range(self.raw_data_per_packet_channel):
            self.raw_data_index_base = np.append(self.raw_data_index_base, temp_index + 9 + i)
        self.raw_data_index_base = np.sort(self.raw_data_index_base)
        self.raw_data_index_base = np.array(self.raw_data_index_base, dtype=np.int64)

        """ sensor_ index """
        for i in range(9):
            self.sensor_index =  np.append(self.sensor_index ,temp_index + 0 + i)
        self.sensor_index = np.sort(self.sensor_index)
        self.sensor_index = np.array(self.sensor_index, dtype=np.int64)

    def LSM6DS3_accelData_in_g(self, x): # 2g range
        return float((x * 0.061 * (2 >> 1)) / 1000 )
    
    def LSM6DS3_gyroData_in_dps(self, x): # 500 range
        gyro_range_divisor = 500 / 125
        return float((x * 4.375 * gyro_range_divisor) / 1000)


    def DAC(self ,x ,raw=True, two_complement=False): 
        if raw:
            if(two_complement):
                if (int(x, 16) < int('8000', 16)): # positive value
                    return int(x, 16)
                else: # negative value
                    a = int(x, 16) 
                    return a - 2**(len(x) * 4)
            else:
                return int(x ,16) # n
        else:
            return (float(int(x ,16) * self.DAC_resolution) - 1.225) / 192 * 1000 * 1000  # uV 放大 192 倍 use unsigned offset 

    def timestamp_calibration(self, x, error_per_ms=30000):
        """ input: system on /ms :positive: delayed error; negative: advanced error """
        return (x + x // error_per_ms) # 每30秒,慢1ms int value
       

    def flush(self):
        self.port.flushInput()


    def calc_SpikeThreshold(self ,x):
        """的数据计算一次threshold"""
        x = np.array(x ,dtype=np.float32)
        return 4 * np.median(np.abs(x) / 0.6745)

    def run(self): # re-write the run method of Qthread
        #  asyncio.run(self.serial_main_run())
        self.read_data()


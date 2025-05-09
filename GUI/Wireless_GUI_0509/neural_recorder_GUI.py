from PyQt6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
    QLineEdit, QMainWindow, QMenuBar, QPushButton,
    QSizePolicy, QSpinBox, QStatusBar, QTextBrowser,
    QVBoxLayout, QWidget ,QMessageBox, QDialog)
from PyQt6.QtGui import QFont

from neural_reader import SerialPort ,my_gaussian_filter1d, LFP_filter
import warnings

import neural_recorder_main_ui as UI
""" pyQtgraph strolling plot"""
"""
Various methods of drawing scrolling plots.
"""
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer
import serial
import serial.tools.list_ports
import threading
import sys
import os
from PyQt6 import QtCore, QtWidgets
import time
from multiprocessing import Process ,Queue
from scipy.fftpack import fft

"""main class"""
class ESBMainWindow(UI.MainWindow):
    def __init__(self):
        super(ESBMainWindow ,self).__init__()

        """ hyper """
        self.Auto_ST_Update = False
        self.Auto_ST_Update_flag = False
        self.channel_panding = None
        self.single_update_data_size = 0
        self.colorList = ['#e6194B', '#3cb44b', '#ffe119', '#4363d8', 
                          '#f58231', '#42d4f4', '#f032e6', '#fabed4', 
                          '#469990', '#dcbeff', '#9A6324', '#fffac8', 
                          '#800000', '#aaffc3', '#000075', '#a9a9a9', 
                          '#ffffff', '#000000'] # pink cyan red
        self.IMUaccle_name = ['Accl_X' ,'Accl_Y' ,'Accl_Z']
        self.IMUgryo_name  = ['Gryo_X' ,'Gryo_Y' ,'Gryo_Z']

        self.current_sample_mode = 0 

        """ init params """
        # system
        self.mSerial = None
        self.t1 = None
        self.curr_active_ports = None
        self.pen1 = pg.mkPen(color=(255, 0, 0))
        ## sample rate
        self.lfp_sample_rate = 1000 # 1khz default
        self.spike_sample_rate = 20833 # 20khz default
        self.spike_raster_bin = 18
        ## display lengths
        self.chart_x_length_s = 10 # 10s
        self.update_packets_num = 0  # genarated data points when GUI update is enabled; determined by @param GUIUpdateInterval ; packets number
        self.lfp_display_data_num = self.lfp_sample_rate * self.chart_x_length_s # 在plot中一次展示的windows的个数,通过采样频率来确定
        self.spike_display_data_num = self.spike_sample_rate * self.chart_x_length_s // 5
        self.spike_raster_display_data_num = self.spike_display_data_num // self.spike_raster_bin  // 5
        self.spike_channel_num = 16
        
        ################# spike raw data mode 1
        self.ring_spike_pointer = 0
        self.spike_x = np.arange(0, self.spike_display_data_num, 1)
        self.spike_raw_data = np.full((1 ,self.spike_display_data_num) ,np.nan)
        self.raw_spike_threshod = np.full((self.spike_channel_num ,self.spike_display_data_num) ,np.nan) # Spike threshold

        ####### spike events raster recording in 17KHz sample rate; Figure 1
        self.ring_spike_raster_pointer = 0
        self.spike_raster_x = np.arange(0, self.spike_raster_display_data_num, 1)
        self.spike_raster_data = np.full((self.spike_channel_num ,self.spike_raster_display_data_num) ,np.nan)

        ####### Spike rate 
        self.SR_value = np.full((1 ,self.spike_raster_display_data_num) ,np.nan) # using the slided average to cale the spiking rate 

        ###### counters
        self.spikemisspackets_mode_1 = 0
        self.spikeaccumulpackets_mode_1 = 0
        self.spike_timestamp_note = 0

        ###### params
        self.spike_raw_channel = 0 # raw data display channel

        ################# LFP raw data mode 0 
        self.separate_interval = 1000 
        self.ring_lfp_pointer = 0
        self.LFP_x = np.arange(0, self.lfp_display_data_num, 1)
        self.LFP_raw_data =np.full((self.spike_channel_num ,self.lfp_display_data_num) ,np.nan)
        self.lfpmisspackets = 0 # recording the number of missed packets every GUI update events
        self.lfpaccumulpackets = 0 # recording received packets number

        self.lfp_filter_length = self.lfp_sample_rate * 2 # 2s data length
        self.lfp_filter_buffer = np.full((self.spike_channel_num ,self.lfp_filter_length) ,np.nan)

        ################# spike mode 2 
        self.separate_interval_spike = 1000
        self.spike_mode2_curr_channel = [0 for _ in range(16)]
        self.ring_spike_mode2_pointer = 0
        self.spike_mode2_x = np.arange(0, self.spike_display_data_num, 1)
        self.spike_mode2_raw_data =np.full((self.spike_channel_num ,self.spike_display_data_num) ,np.nan)
        self.spike_moide2_misspackets = 0 # recording the number of missed packets every GUI update events
        self.spike_mode2_accumulpackets = 0 # recording received packets number

        self.reinit_rawdata_mode2 = False
        self.reinit_rawdata_mode2_temp = 0

        ############### Other sensors
        self.ring_LSR_pointer = 0
        self.LSR_display_data_num = 1000 
        self.LSR_timestamp = np.arange(0, self.LSR_display_data_num, 1) 
        self.CHG_stat = np.full((1 ,self.LSR_display_data_num) ,np.nan) # battery charging status
        self.PPM_stat = np.full((1 ,self.LSR_display_data_num) ,np.nan) # battery_PPM
        self.PG_stat = np.full((1 ,self.LSR_display_data_num) ,np.nan) # Power status
        self.IMUdata = np.full((6 ,self.LSR_display_data_num) ,np.nan) # AcclX,Y,Z ,geclo X ,Y,Z

        # current battery status
        self.CHG = 0
        self.PPM = 0
        self.PG = 0
        
        # Spike threshold auto update buffer
        self.calcST_counter = [0 for _ in range(self.spike_channel_num)]
        self.computedST = [0 for _ in range(self.spike_channel_num)]
        self.updateSTflag = [0 for _ in range(self.spike_channel_num)]

        """ build  widgets containing these charts """
        pg.setConfigOption('background', 'k')
        pg.setConfigOption('foreground', 'w')
        
        """ raw data graph spike mode 1 """
        # raw data graph: figure 3; two axis ; raw data and threshold data ; spike dat
        self.SPIKE_view_channel = pg.ViewBox() # 定义一个视图框
        self.spike_channel = pg.GraphicsView() # 设置 绘图
        self.SPIKE_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.spike_channel.setCentralWidget(self.SPIKE_layout_channel) # 将绘图区域设置为视图的中心组件

        self.spike_pI_channel = pg.PlotItem() # 定义一条曲线
        self.spike_pI_channel.setTitle('channel 0-15')
        self.spike_v1_channel = self.spike_pI_channel.vb # 得到曲线的视图层
        self.SPIKE_layout_channel.addItem(self.spike_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.SPIKE_layout_channel.scene().addItem(self.SPIKE_view_channel)

        self.SPIKE_view_channel.setXLink(self.spike_v1_channel)
        self.spike_pI_channel.getAxis("left").setLabel('spike raw data/uv', color='#FFC0CB')
        self.spike_pI_channel.addLegend()

        # updating indicate lines: infiniteLine  
        self.spike_updating_indicater_mode_1 = pg.InfiniteLine(movable=False, label='', angle=90, pen=pg.mkPen(color='w', width=3), 
                                  labelOpts={'position':0.9, 'color':'y', 'fill': (200,200,200,50)})
        self.spike_v1_channel.addItem(self.spike_updating_indicater_mode_1)

        self.raw_threshold_channel = pg.PlotCurveItem(None ,None ,pen='#DC143C') # threshold line
        self.spike_v1_channel.addItem(self.raw_threshold_channel)

        self.raw_dataline_channel = pg.PlotCurveItem(None, None ,name='channel 0-15') # raw data of one channel line
        self.spike_v1_channel.addItem(self.raw_dataline_channel)
        self.spike_v1_channel.enableAutoRange(axis= pg.ViewBox.XYAxes ,enable = True)

        self.spike_v1_channel.setLimits(xMin=0, xMax=self.spike_display_data_num, yMin=-2000, yMax=2000) # 1mv range
        self.spike_v1_channel.setXRange(0 ,self.spike_display_data_num)
        
        """ spiking rate and raster graph mode 1 """
        self.SR_view_channel = pg.ViewBox() # 定义一个视图框
        self.SR_channel = pg.GraphicsView() # 设置 绘图
        self.SR_channel.setWindowTitle('SR data 0-15 channels')
        self.SR_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.SR_channel.setCentralWidget(self.SR_layout_channel) # 将绘图区域设置为视图的中心组件
        
        self.SR_pI_channel = pg.PlotItem() # 定义一条曲线
        self.SR_v1_channel = self.SR_pI_channel.vb # 得到曲线的视图层
        self.SR_layout_channel.addItem(self.SR_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.SR_layout_channel.scene().addItem(self.SR_view_channel)
        self.SR_view_channel.setXLink(self.SR_v1_channel)
        self.SR_pI_channel.getAxis("left").setLabel('SR', color='#FFC0CB')
        self.SR_pI_channel.addLegend()

        # updating indicate lines: infiniteLine  
        self.spike_raster_updating_indicater_mode_1 = pg.InfiniteLine(movable=False, label='', angle=90, pen=pg.mkPen(color='w', width=3), 
                                  labelOpts={'position':0.9, 'color':'y', 'fill': (200,200,200,50)})
        self.SR_v1_channel.addItem(self.spike_raster_updating_indicater_mode_1)

        # spike rate lines
        self.spike_SR_channel = pg.PlotCurveItem(None, None,pen='#FFFFFF')
        self.SR_v1_channel.addItem(self.spike_SR_channel)

        # raster ticks setting
        raster_ticks = {
            int(value):'channel{}'.format(channel) for value, channel in 
            zip(np.arange(0, self.spike_channel_num, 1), range(16))
        }
        self.SR_pI_channel.getAxis("left").setTicks([raster_ticks.items()])
        font = QFont()
        font.setBold(True)
        font.setPointSize(6)
        self.SR_pI_channel.getAxis("left").setTickFont(font)

        # raster lines
        self.spike_raster_channel = []
        for i in range(self.spike_channel_num):
            self.spike_raster_channel.append(pg.ScatterPlotItem(None, None,pen='#FFFFFF'))
            self.spike_raster_channel[i].setSymbol('arrow_up')
            self.SR_v1_channel.addItem(self.spike_raster_channel[i])
        self.SR_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        self.SR_v1_channel.setLimits(xMin=0, xMax=self.spike_raster_display_data_num, yMin=-1, yMax=16) # 1mv range
        self.SR_v1_channel.setYRange(-1 ,16) 
        self.SR_v1_channel.setXRange(0 ,self.spike_raster_display_data_num) 

        """ LFP graph mode 0"""
        self.LFP_view_channel = pg.ViewBox() # 定义一个视图框
        self.LFP_channel = pg.GraphicsView() # 设置 绘图
        self.LFP_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.LFP_channel.setCentralWidget(self.LFP_layout_channel) # 将绘图区域设置为视图的中心组件
        
        self.LFP_pI_channel = pg.PlotItem() 
        self.LFP_pI_channel.setTitle('LFP data 0-15 channels')
        self.LFP_v1_channel = self.LFP_pI_channel.vb # 得到曲线的视图层
        self.LFP_layout_channel.addItem(self.LFP_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.LFP_layout_channel.scene().addItem(self.LFP_view_channel)
        self.LFP_view_channel.setXLink(self.LFP_v1_channel)
        self.LFP_pI_channel.getAxis("left").setLabel('LFP 1kHz', color='#FFC0CB')
        self.LFP_pI_channel.addLegend()
         
        # LFP lines
        self.LFP_raw_channel = []
        for i in range(self.spike_channel_num):
            self.LFP_raw_channel.append(pg.PlotCurveItem(None, None,pen='#FFFFFF'))
            self.LFP_v1_channel.addItem(self.LFP_raw_channel[i])
        # updating indicate lines: infiniteLine  
        self.updating_indicater = pg.InfiniteLine(movable=False, label='', angle=90, pen=pg.mkPen(color='w', width=3), 
                                  labelOpts={'position':0.99, 'color':'y', 'fill': (200,200,200,50)})
        self.LFP_v1_channel.addItem(self.updating_indicater)
        # lfp ticks setting
        lfp_ticks = {
            int(value):'channel{}'.format(channel) for value, channel in 
            zip(np.arange(0, self.spike_channel_num * self.separate_interval, self.separate_interval), range(16))
        }
        self.LFP_pI_channel.getAxis("left").setTicks([lfp_ticks.items()])

        self.LFP_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        self.LFP_v1_channel.setLimits(xMin=0, xMax=self.lfp_display_data_num, yMin=-self.separate_interval, yMax=self.spike_channel_num * self.separate_interval)
        self.LFP_v1_channel.setYRange(1 ,self.spike_channel_num * self.separate_interval) 
        self.LFP_v1_channel.setXRange(0 ,self.lfp_display_data_num)

        """ 4 channel AP data spike mode 2"""
        self.AP_view_channel = pg.ViewBox() # 定义一个视图框
        self.AP_channel = pg.GraphicsView() # 设置 绘图
        self.AP_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.AP_channel.setCentralWidget(self.AP_layout_channel) # 将绘图区域设置为视图的中心组件
        
        self.AP_pI_channel = pg.PlotItem() 
        self.AP_pI_channel.setTitle('AP data 0-15 channels')
        self.AP_v1_channel = self.AP_pI_channel.vb # 得到曲线的视图层
        self.AP_layout_channel.addItem(self.AP_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.AP_layout_channel.scene().addItem(self.AP_view_channel)
        self.AP_view_channel.setXLink(self.AP_v1_channel)
        self.AP_pI_channel.getAxis("left").setLabel('AP 20kHz', color='#FFC0CB')
        self.AP_pI_channel.addLegend()
         
        # AP lines
        self.AP_raw_channel = []
        for i in range(self.spike_channel_num):
            self.AP_raw_channel.append(pg.PlotCurveItem(None, None,pen='#FFFFFF'))
            self.AP_v1_channel.addItem(self.AP_raw_channel[i])
        # updating indicate lines: infiniteLine  
        self.AP_updating_indicater = pg.InfiniteLine(movable=False, label='', angle=90, pen=pg.mkPen(color='w', width=3), 
                                  labelOpts={'position':0.99, 'color':'y', 'fill': (200,200,200,50)})
        self.AP_v1_channel.addItem(self.AP_updating_indicater)

        # spike ticks setting
        spike_mode2_ticks = {
            int(value):'channel{}'.format(channel) for value, channel in 
            zip(np.arange(0, self.spike_channel_num * self.separate_interval_spike, self.separate_interval_spike), range(16))
        }
        self.AP_pI_channel.getAxis("left").setTicks([spike_mode2_ticks.items()])

        self.AP_v1_channel.setLimits(xMin=0, xMax=self.spike_display_data_num, yMin=-self.separate_interval_spike, yMax=self.spike_channel_num * self.separate_interval_spike)
        self.AP_v1_channel.setYRange(1 ,self.spike_channel_num * self.separate_interval_spike) 
        self.AP_v1_channel.setXRange(0 ,self.spike_display_data_num)
        
        """ other sensors graph """
        self.IMU_yrange_accle = 2
        # accle 3-axis
        self.accl_view_channel = pg.ViewBox() # 定义一个视图框
        self.accl_channel = pg.GraphicsView() # 设置 绘图
        self.accl_channel.setWindowTitle('accl data')
        self.accl_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.accl_channel.setCentralWidget(self.accl_layout_channel) # 将绘图区域设置为视图的中心组件
        self.accl_pI_channel = pg.PlotItem() # 定义一条曲线
        self.accl_v1_channel = self.accl_pI_channel.vb # 得到曲线的视图层
        self.accl_layout_channel.addItem(self.accl_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.accl_layout_channel.scene().addItem(self.accl_view_channel)
        self.accl_view_channel.setXLink(self.accl_v1_channel)
        self.accl_pI_channel.getAxis("left").setLabel('accl/g', color='#FFC0CB')
        self.accl_pI_channel.addLegend()
        
        self.IMU_accl_channel = [] ## accle 3-axis lines
        for i in range(3):
            self.IMU_accl_channel.append(pg.PlotCurveItem(None, None,pen=self.colorList[i] ,name=self.IMUaccle_name[i]))
            self.accl_v1_channel.addItem(self.IMU_accl_channel[i])
        
        self.accle_updating_indicater = pg.InfiniteLine(movable=False, label='{value:0.2f}', angle=90, pen=pg.mkPen(color='w', width=3), 
                                  labelOpts={'position':0.9, 'color':(150,0,0), 'fill': (200,200,200,50)})
        self.accl_v1_channel.addItem(self.accle_updating_indicater)
        
        self.accl_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        self.accl_v1_channel.setLimits(xMin=0, xMax=self.LSR_display_data_num, yMin=-self.IMU_yrange_accle, yMax=self.IMU_yrange_accle) # 1mv range
        self.accl_v1_channel.setXRange(0 ,self.LSR_display_data_num) 
        self.accl_v1_channel.setYRange(-self.IMU_yrange_accle ,self.IMU_yrange_accle)
        
        """ addWidget """
        self.lfp_tab.chart_container_layout.addWidget(self.LFP_channel)
        self.spike1ch_tab.chart_container_layout.addWidget(self.spike_channel)
        self.raster_tab.chart_container_layout.addWidget(self.SR_channel)
        self.imu_tab.chart_container_layout.addWidget(self.accl_channel)
        self.spike4ch_tab.chart_container_layout.addWidget(self.AP_channel)

        """ callback function """
        self.lfp_tab.start_save_button.clicked.connect(self.start_save_lfp)
        self.lfp_tab.stop_save_button.clicked.connect(self.stop_save_lfp)
        self.start_sampling_button.clicked.connect(self.sample_start)
        self.stop_sampling_button.clicked.connect(self.sample_stop)
        self.sampling_mode_combo.currentIndexChanged.connect(self.sample_mode_switch)
        self.spike4ch_tab.send_channels_button.clicked.connect(self.spike_channel_switch_mode2)
        self.spike1ch_tab.send_command_button.clicked.connect(self.spike_channel_switch_mode1)
        self.raster_tab.auto_threshold_button.clicked.connect(self.Auto_threshold_update)
        self.raster_tab.channel_combo.currentIndexChanged.connect(self.spike_threshold_set)
        self.raster_tab.threshold_combo.currentIndexChanged.connect(self.spike_threshold_set)
        self.update_battery_button.clicked.connect(self.battery_mode_setting)
        # self.lfp_tab.enable_filter_button.clicked.connect(self.lfp_filter_on)
        # self.lfp_tab.disable_filter_button.clicked.connect(self.lfp_filter_off)
        
    # data update function
    def update_plot_data(self, data):  # 注意：实际的一次更新得到的包的数量是在浮动的根据线程处理的速度
        if self.curr_active_ports is not None:
            self.raw_data_generator(self.curr_active_ports, data)
            if(int(data[0][0]) == 0):
                """ LFP raw data update """
                # # update infinited line
                self.updating_indicater.setPos(self.ring_lfp_pointer) # span (0, 1)
                self.updating_indicater.label.setFormat('loss:{}/{}'.format(self.lfpmisspackets, self.lfpaccumulpackets))
                ## update rssi
                self.update_rssi(self.mSerial.rssi)
                ## update loss rate
                self.update_packet_loss(round(self.lfpmisspackets /(self.lfpaccumulpackets + self.lfpmisspackets + 1), 2) * 100) # +1 防止divide zero
                # update data
                for i in range(16): # diff color diff channels separate_interval
                    self.LFP_raw_channel[i].setData(self.LFP_x, self.LFP_raw_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1}))   
            
            elif(int(data[0][0]) == 1):
                """ spike data mode 1 """ 
                #### raw data update
                # update indicte line
                self.spike_updating_indicater_mode_1.setPos(self.ring_spike_pointer)
                self.spike_updating_indicater_mode_1.label.setFormat('loss: {}/{} time: {} s'.format(self.spikemisspackets_mode_1, self.spikeaccumulpackets_mode_1, self.spike_timestamp_note // 1000))
                ## update rssi
                self.update_rssi(self.mSerial.rssi)
                ## update loss rate
                self.update_packet_loss(round(self.spikemisspackets_mode_1 /(self.spikemisspackets_mode_1 + self.spikeaccumulpackets_mode_1 + 1), 2) * 100)
                # update channels index
                self.spike_pI_channel.setTitle('channel {}'.format(self.spike_raw_channel))
                # update data
                self.raw_dataline_channel.setData(self.spike_x, self.spike_raw_data[0] ,pen=pg.mkPen({'color': 'w' ,'width':1}))

                #### raster data update
                # update infinited line
                self.spike_raster_updating_indicater_mode_1.setPos(self.ring_spike_raster_pointer)
                # update data
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    for i in range(16): # diff color diff channels separate_interval
                        self.spike_raster_data[i][self.spike_raster_data[i] == 0] = -1
                        self.spike_raster_channel[i].setData(self.spike_raster_x, self.spike_raster_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1}))   
                # update spike rate data
                self.spike_raster_data[self.spike_raster_data == -1] = 0
                self.SR_value[0] = my_gaussian_filter1d(np.sum(self.spike_raster_data ,axis=0) ,sigma=10)
                self.spike_SR_channel.setData(self.spike_raster_x ,self.SR_value[0]  ,pen=pg.mkPen({'color': 'w' ,'width':2}))  # ,fillLevel=10, fillBrush=(255,255,255,30)

                """ auto update spike threshold """
                # 循环的自动采样不同channel的raw data 来 时刻更新 spike threhsold
                if(self.Auto_ST_Update):
                    self.Auto_ST_Update_flag += self.single_update_data_size
                    if(self.Auto_ST_Update_flag >= self.spike_display_data_num): # pending enough raw data
                        # reset pending data flag
                        self.Auto_ST_Update_flag = 0
                        # set the next channel
                        self.spike1ch_tab.channel_combo.setCurrentIndex(self.channel_panding) 
                        # update the threshold
                        self.spike_channel_switch_mode1()
                        self.channel_panding += 1
                        if(self.channel_panding >= 16):
                            self.Auto_ST_Update = False
                            self.channel_panding = 0
                            self.Auto_ST_Update_flag = 0
                            self.statusBar().showMessage("Note:Auto Spike Threshold completed!")
            
            elif(int(data[0][0]) == 2):
                """ spike data mode 2 """ 
                # # update infinited line
                self.AP_updating_indicater.setPos(self.ring_spike_mode2_pointer) # span (0, 1)
                self.AP_updating_indicater.label.setFormat('loss_packets:{}/{} time: {} s'.format(self.spike_moide2_misspackets, self.spike_mode2_accumulpackets, self.spike_timestamp_note // 1000))
                ## update rssi
                self.update_rssi(self.mSerial.rssi)
                ## update loss rate
                self.update_packet_loss(round(self.spike_moide2_misspackets /(self.spike_moide2_misspackets + self.spike_mode2_accumulpackets + 1), 2) * 100)

                for i in range(16): # diff color diff channels separate_interval
                    # update data
                    """ upper and lower band """
                    if(self.spike_mode2_curr_channel[i] != 0):
                        self.reinit_rawdata_mode2_temp += 1
                        self.AP_raw_channel[i].setData(self.spike_mode2_x, self.spike_mode2_raw_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1}))   
                    else:
                        # re-init raw data
                        self.spike_mode2_raw_data[i] = np.full((1 ,self.spike_display_data_num) ,np.nan)
                        self.AP_raw_channel[i].setData(self.spike_mode2_x, self.spike_mode2_raw_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1}))
  

            """ LSR data update """ 
            self.accle_updating_indicater.setPos(self.ring_LSR_pointer) # span (0, 1)
            if(self.ring_LSR_pointer >= self.LSR_display_data_num):
                self.ring_LSR_pointer = 0
            # IMU data
            for imu_channel in range(3):
                self.IMU_accl_channel[imu_channel].setData(self.LSR_timestamp ,self.IMUdata[imu_channel] ,name=self.IMUaccle_name[imu_channel] ,
                                                 pen=pg.mkPen({'color': self.colorList[imu_channel] ,'width':1}),symbol='o')
            # battery data
            self.update_battery_indicator(self.CHG, self.PPM, self.PG)
             
    def raw_data_generator(self ,port, data):
        """
        update all data array via ring buffer
        @data:
        lfp_mode_0: [[0], self.lfptimestamp_GUI, self.lfpdata_GUI, self.sensordata_GUI]
        spike_mode_1: [[1, self.spike_channel_index_mode1], self.spiketimestamp_GUI, self.spikedata_GUI, self.sensordata_GUI, self.spikerasterdata_GUI]
        """
        if port is not None:
            if(int(data[0][0]) == 0):
                """ LFP raw data figure 1"""
                lfp_timestamp = np.array(data[1])
                raw_data = np.array(data[2])
                # statitic dropped packets
                temp_loss = np.diff(lfp_timestamp) 
                temp_loss = temp_loss[(temp_loss > self.mSerial.LFP_max_interval) | (temp_loss <= 0)]
                loss_packets_value = len(temp_loss // (self.mSerial.LFP_max_interval - 1))
                self.lfpmisspackets +=  loss_packets_value
                self.lfpaccumulpackets += len(lfp_timestamp)

                # 每save file 10次就重新统计丢失的包的数量
                if(self.lfpaccumulpackets >= (self.mSerial.file_size) * 10):
                    self.lfpaccumulpackets = 0
                    self.lfpmisspackets = 0

                # # filter_buff update
                # self.lfp_filter_buffer = np.roll(self.lfp_filter_buffer, -1*len(raw_data[0]), axis=1)
                # self.lfp_filter_buffer[:, -len(raw_data[0]):] = raw_data

                # update figure data
                endpoint = self.ring_lfp_pointer + len(raw_data[0])
                if(endpoint > self.lfp_display_data_num):
                    temp_onset = endpoint - self.lfp_display_data_num
                    for channel_num in range(16):
                        temp_vdd = raw_data[channel_num] + channel_num * self.separate_interval
                        self.LFP_raw_data[channel_num][self.ring_lfp_pointer:] = temp_vdd[0:-temp_onset]
                        self.LFP_raw_data[channel_num][0:temp_onset] = temp_vdd[-temp_onset:]
                    self.ring_lfp_pointer = temp_onset
                else:
                    for channel_num in range(16):
                        self.LFP_raw_data[channel_num][self.ring_lfp_pointer:endpoint] = raw_data[channel_num] + channel_num * self.separate_interval
                    self.ring_lfp_pointer = endpoint # update indicater

                # filter 只滤波pointer 之前的所有数据
                if(not self.lfp_tab.enable_filter_button.isEnabled() and self.ring_lfp_pointer > 0):
                    for channel_num in range(16):
                        self.LFP_raw_data[channel_num][0:self.ring_lfp_pointer] = LFP_filter(self.LFP_raw_data[channel_num][0:self.ring_lfp_pointer] - channel_num * self.separate_interval, 
                                                                                             self.lfp_tab.low_cutoff.currentText(), self.lfp_tab.high_cutoff.currentText()) + channel_num * self.separate_interval

            
            elif(int(data[0][0]) == 1):
                """ spike raw data + raster data mode 1 """
                self.spike_raw_channel = data[0][1]
                spike_timestamp_mode_1 = np.array(data[1])
                spike_raw_data_mode_1 = np.array(data[2])
                spike_raster_data_mode_1 = np.array(data[4], dtype=np.float32)
                # curr timestamp
                self.spike_timestamp_note = spike_timestamp_mode_1[0]
                # statitic dropped packets
                temp_loss = np.diff(spike_timestamp_mode_1) 
                temp_loss = temp_loss[(temp_loss > self.mSerial.Spike_max_interval) | (temp_loss <= 0)]
                loss_packets_value = len(temp_loss // (self.mSerial.Spike_max_interval - 1))
                self.spikemisspackets_mode_1 +=  loss_packets_value
                self.spikeaccumulpackets_mode_1 += len(spike_timestamp_mode_1)
                # 每save file一次就重新统计丢失的包的数量
                if(self.spikeaccumulpackets_mode_1 >= self.mSerial.file_size * 10):
                    self.spikeaccumulpackets_mode_1 = 0
                    self.spikemisspackets_mode_1 = 0
                
                # update raw data
                self.single_update_data_size = len(spike_raw_data_mode_1)
                endpoint = self.ring_spike_pointer + len(spike_raw_data_mode_1)
                if(endpoint > self.spike_display_data_num):
                    temp_onset = endpoint - self.spike_display_data_num
                    
                    self.spike_raw_data[0][self.ring_spike_pointer:] = spike_raw_data_mode_1[0:-temp_onset]
                    self.spike_raw_data[0][0:temp_onset] = spike_raw_data_mode_1[-temp_onset:]
                    self.ring_spike_pointer = temp_onset
                else:
                    self.spike_raw_data[0][self.ring_spike_pointer:endpoint] = spike_raw_data_mode_1
                    self.ring_spike_pointer = endpoint # update indicater

                # update raster data
                endpoint = self.ring_spike_raster_pointer + len(spike_raster_data_mode_1[0])
                if(endpoint > self.spike_raster_display_data_num):
                    temp_onset = endpoint - self.spike_raster_display_data_num
                    for channel_num in range(16):
                        temp_vdd = spike_raster_data_mode_1[channel_num] * (channel_num) # separate value
                        self.spike_raster_data[channel_num][self.ring_spike_raster_pointer:] = temp_vdd[0:-temp_onset]
                        
                        self.spike_raster_data[channel_num][0:temp_onset] = temp_vdd[-temp_onset:]
                    self.ring_spike_raster_pointer = temp_onset
                else:
                    for channel_num in range(16):
                        self.spike_raster_data[channel_num][self.ring_spike_raster_pointer:endpoint] = spike_raster_data_mode_1[channel_num] * (channel_num)
                    self.ring_spike_raster_pointer = endpoint # update indicater
            
            elif(int(data[0][0]) == 2):
                """ spike raw data AP mode 2 """
                spike_timestamp = np.array(data[1])
                spikeraw_data =data[2]
                 # curr timestamp
                self.spike_timestamp_note = spike_timestamp[0]

                # statitic dropped packets
                temp_loss = np.diff(spike_timestamp) 
                temp_loss = temp_loss[(temp_loss > self.mSerial.Spike_max_interval) | (temp_loss <= 0)]
                loss_packets_value = len(temp_loss // (self.mSerial.Spike_max_interval - 1))
                self.spike_moide2_misspackets +=  loss_packets_value
                self.spike_mode2_accumulpackets += len(spike_timestamp)

                # 每save file一次就重新统计丢失的包的数量
                if(self.spike_mode2_accumulpackets >= self.mSerial.file_size * 10):
                    self.spike_mode2_accumulpackets = 0
                    self.spike_moide2_misspackets = 0

                # update figure data
                self.spike_mode2_curr_channel = []
                for ii in range(16):
                    self.spike_mode2_curr_channel.append(len(spikeraw_data[ii]))
                
                endpoint = self.ring_spike_mode2_pointer + max(self.spike_mode2_curr_channel)
                if(endpoint > self.spike_display_data_num):
                    temp_onset = endpoint - self.spike_display_data_num
                    for channel_num in range(16):
                        if(self.spike_mode2_curr_channel[channel_num] != 0):
                            temp_vdd = np.array(spikeraw_data[channel_num]) + channel_num * self.separate_interval
                            self.spike_mode2_raw_data[channel_num][self.ring_spike_mode2_pointer:] = temp_vdd[0:-temp_onset]
                            self.spike_mode2_raw_data[channel_num][0:temp_onset] = temp_vdd[-temp_onset:]
                    self.ring_spike_mode2_pointer = temp_onset
                else:
                    for channel_num in range(16):
                        if(self.spike_mode2_curr_channel[channel_num] == max(self.spike_mode2_curr_channel)):
                            self.spike_mode2_raw_data[channel_num][self.ring_spike_mode2_pointer:endpoint] = np.array(spikeraw_data[channel_num]) + channel_num * self.separate_interval
                    self.ring_spike_mode2_pointer = endpoint # update indicater
                pass


            """ sensing data 9 data """
            sensors_data = np.array(data[3], dtype=np.float32)
            sensor_end_point = self.ring_LSR_pointer + len(sensors_data[0])

            self.CHG = int(sensors_data[6][-1])
            self.PPM = int(sensors_data[7][-1])
            self.PG = int(sensors_data[8][-1])
            if(sensor_end_point > self.LSR_display_data_num):
                temp_onset = sensor_end_point - self.LSR_display_data_num
                for i in range(6):
                    self.IMUdata[i][self.ring_LSR_pointer:] = sensors_data[i][0:-temp_onset]
                    self.IMUdata[i][0:temp_onset] = sensors_data[i][-temp_onset:]

                self.CHG_stat[0][self.ring_LSR_pointer:] = sensors_data[6][0:-temp_onset]
                self.CHG_stat[0][0:temp_onset] = sensors_data[6][-temp_onset:]

                self.PPM_stat[0][self.ring_LSR_pointer:] = (sensors_data[7][0:-temp_onset])
                self.PPM_stat[0][0:temp_onset] = sensors_data[7][-temp_onset:] 

                self.PG_stat[0][self.ring_LSR_pointer:] = (sensors_data[8][0:-temp_onset])
                self.PG_stat[0][0:temp_onset] = sensors_data[8][-temp_onset:] 
                
                self.ring_LSR_pointer = temp_onset
            else:
                try:
                    for i in range(6):
                        self.IMUdata[i][self.ring_LSR_pointer:sensor_end_point] = sensors_data[i]
                    self.CHG_stat[0][self.ring_LSR_pointer:sensor_end_point] = sensors_data[6]
                    self.PPM_stat[0][self.ring_LSR_pointer:sensor_end_point] = sensors_data[7]
                    self.PG_stat[0][self.ring_LSR_pointer:sensor_end_point] = sensors_data[8]
                except:
                    print(sensors_data[i])
                self.ring_LSR_pointer = sensor_end_point


    """callback function"""
    def set_connected_port(self, port):
        """设置连接的串口"""
        self.curr_active_ports = port
        self.statusBar().showMessage(f"已连接到 {port}")
        try:
        # start read data from Serial
            self.mSerial = SerialPort(self.curr_active_ports,2000000)
            self.mSerial.load_parameters() # 加载保存的参数，例如 当前系统的时间戳
            self.mSerial.port_open()
            self.mSerial.GUIUpdate.connect(self.update_plot_data)
            self.mSerial.start()
        except:
            print(sys.exc_info())
            QMessageBox.warning(self, "Warning", "Serial Port open failed")
            pass
    
    def start_save_lfp(self):
        self.mSerial.save_file_lfp_flag = True
        self.mSerial.lfp_file_addr = self.lfp_tab.file_path_label.text()
    
    def stop_save_lfp(self):
        self.mSerial.save_file_lfp_flag = False
        self.mSerial.lfp_file_addr = ""

    def sample_start(self):
        self.mSerial.flush()
        self.open_command = [0x01 ,0x00] 
        self.mSerial.send_data(self.open_command)

    def sample_stop(self):
        self.close_command = [0x02 ,0x00] # invalid sample mode
        self.mSerial.send_data(self.close_command)

    def sample_mode_switch(self): # 切换选项卡的时候就会触发 模式的改变
        mode = self.sampling_mode_combo.currentIndex()
        self.err = self.mSerial.send_data([0x00 ,0x03, int(hex(mode) ,16), 0x00])
        self.current_sample_mode = mode
        # 根据选择的采样模式跳转到对应选项卡
        if self.current_sample_mode == 0:
            self.tab_widget.setCurrentIndex(0)  # 16通道LFP
        elif self.current_sample_mode == 1:
            self.tab_widget.setCurrentIndex(4)  #  单通道Spike
        elif self.current_sample_mode == 2:
            self.tab_widget.setCurrentIndex(1)  # 4通道Spike
    
    def spike_channel_switch_mode1(self):
        if (self.current_sample_mode >= 0):
            self.channel_command = [0x00, 0x04 ,  0x00 ,0x00,    0x00, 0x00] 
            # recording raw channel
            self.channel_command[-4] = int(hex(self.spike1ch_tab.channel_combo.currentIndex()) ,16)
            # threshold; 注意这里需要等待 改通道的数据全部刷新完成后再使用 
            temp_threshold = self.mSerial.calc_SpikeThreshold(self.spike_raw_data[0])
            self.statusBar().showMessage("Threshold update: channel {} threshold {} uV".format(self.spike_raw_channel, temp_threshold))

            temp_threshold = int((temp_threshold / 1000 / 1000 * 192 + 1.225) / self.mSerial.DAC_resolution)
            temp_threshold = temp_threshold - int('0x8000', 16)
            if(temp_threshold >= int('0x8000', 16)):
                temp_threshold = 0
                self.statusBar().showMessage("Error:Auto Spike Threshold overflow!")
            
            temp_threshold = hex(temp_threshold).replace('0x' ,'').zfill(4)
            self.channel_command[-1] = int(temp_threshold[0:2] ,16)
            self.channel_command[-2] = int(temp_threshold[2:4] ,16)

            self.err = self.mSerial.send_data(self.channel_command)
        else:
            QMessageBox.warning(self, "Warning", "Please set the sample mode to Spike Mode 1!")
            pass
    
    def spike_channel_switch_mode2(self):
        self.mode2_channel_command = [0x00 ,0x05 ,0x00 ,0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00] # 4 channels setting
        try:
            temp_mode2 = [combo.currentIndex() for combo in self.spike4ch_tab.channel_combos]
            for i in range(4):
                self.mode2_channel_command[2*(i + 1)] = (int(temp_mode2[i]))
            self.err = self.mSerial.send_data(self.mode2_channel_command)
        except:
            pass   

    def Auto_threshold_update(self):
        if (self.current_sample_mode >= 0):
            self.Auto_ST_Update = True
            self.channel_panding = 0
            self.Auto_ST_Update_flag = 0
            self.statusBar().showMessage("Note:Auto Spike Threshold begining!")
        else:
            QMessageBox.warning(self, "Warning", "Please set the sample mode to Spike Mode 1!")
            pass

    def spike_threshold_set(self): #TODO channel 0, 14 spike raster 有问题可能
        if (self.current_sample_mode >= 0):
            self.channel_command = [0x00, 0x04 ,  0x00 ,0x00,    0x00, 0x00] 
            # recording raw channel
            self.channel_command[-4] = int(hex(self.raster_tab.channel_combo.currentIndex()) ,16)
            # threshold manual setting 
            temp_threshold = int(self.raster_tab.threshold_combo.currentText())
            self.statusBar().showMessage("Threshold update: channel {} threshold {} uV".format(self.spike_raw_channel, temp_threshold))
            # 使用negative的值
            temp_threshold = int((temp_threshold / 1000 / 1000 * 192 + 1.225) / self.mSerial.DAC_resolution) # 得到设置的threshold值（postive）
            temp_threshold = temp_threshold - int('0x8000', 16) # 得到相对0 的threshold
            
            temp_threshold = hex(temp_threshold).replace('0x' ,'').zfill(4)
            self.channel_command[-1] = int(temp_threshold[0:2] ,16)
            self.channel_command[-2] = int(temp_threshold[2:4] ,16)
            self.err = self.mSerial.send_data(self.channel_command)

        else:
            QMessageBox.warning(self, "Warning", "Please set the sample mode to Spike Mode 1!")
            pass
    
    def battery_mode_setting(self):
        self.MP2710_command = [0x03, 0x00 ,  0x00 ,0x00] 
        print("Afadvda")
        # battery_mode
        self.MP2710_command[-2] = int(hex(self.battery_status_combo.currentIndex() + 1) ,16)
        self.err = self.mSerial.send_data(self.MP2710_command)

    # def lfp_filter_on(self):
    #     self.mSerial.GUIUpdateInterval = 100 # TODO 增加更新间隔来增加filter 的窗口
    
    # def lfp_filter_off(self):
    #     self.mSerial.GUIUpdateInterval = 10 



""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
def main():
    """主函数"""
    app = QApplication(sys.argv)

    # 显示连接对话框
    connection_dialog = UI.SerialConnectionDialog()
    if connection_dialog.exec() == QDialog.DialogCode.Accepted:
        # 如果连接成功，显示主窗口
        main_window = ESBMainWindow()
        main_window.set_connected_port(connection_dialog.selected_port)
        main_window.show()
        sys.exit(app.exec())
    else:
        # 如果用户取消连接，退出应用
        sys.exit(0)

if __name__ == "__main__":
    main()


    

from PyQt6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
    QLineEdit, QMainWindow, QMenuBar, QPushButton,
    QSizePolicy, QSpinBox, QStatusBar, QTextBrowser,
    QVBoxLayout, QWidget ,QMessageBox)
from PyQt6.QtGui import QFont

from ESB_reader import SerialPort ,my_gaussian_filter1d
import warnings

import QtESBV3_UI
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

#TODO UI color legend&symbol dont work ; all nan value bug
""" hypo defintion """
Max_pipe = 5 
"""main class"""
class ESBMainWindow(QtWidgets.QMainWindow ,QtESBV3_UI.Ui_MainWindow):
    def __init__(self):
        super(ESBMainWindow ,self).__init__()
        self.setupUi(self)

        # self.guiTimer = 10 # ms
        # self.guidata_queue = gui_data
        # # structure: (commands, data)
        # self.guimess_queue = gui_mess
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

        """ init params """
        # system
        self.mSerial = [None for _ in range(Max_pipe)] # muti serial port 
        self.t1 = [None for _ in range(Max_pipe)] # thread
        self.mSerial_disable = []
        self.curr_active_ports = None
        self.pen1 = pg.mkPen(color=(255, 0, 0))
        self.lfp_sample_rate = 2000 # 2khz default
        self.spike_sample_rate = 18000 # 20khz default
        self.spike_raster_bin = 18
        self.chart_x_length_ms = 10000 # 12s
        self.update_packets_num = 0  # genarated data points when GUI update is enabled; determined by @param GUIUpdateInterval ; packets number
        self.lfp_display_data_num = self.lfp_sample_rate * self.chart_x_length_ms // 1000 # 在plot中一次展示的windows的个数,通过采样频率来确定
        self.spike_display_data_num = self.spike_sample_rate * self.chart_x_length_ms // 1000

        self.spike_raster_display_data_num = self.spike_display_data_num // self.spike_raster_bin // 5

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

        ################# LFP raw data 
        self.separate_interval = 1000 # TODO
        self.saturation_value = 500
        self.ring_lfp_pointer = 0
        self.LFP_x = np.arange(0, self.lfp_display_data_num, 1)
        self.LFP_raw_data =np.full((self.spike_channel_num ,self.lfp_display_data_num) ,np.nan)
        self.lfpmisspackets = 0 # recording the number of missed packets every GUI update events
        self.lfpaccumulpackets = 0 # recording received packets number
        ############### Other sensors
        self.ring_LSR_pointer = 0
        self.LSR_display_data_num = 1000 # TODO
        self.LSR_timestamp = np.arange(0, self.LSR_display_data_num, 1) 
        self.RSOC = np.full((1 ,self.LSR_display_data_num) ,np.nan) # battery RSOC
        self.battery_temp = np.full((1 ,self.LSR_display_data_num) ,np.nan) # battery_temp
        self.IMUdata = np.full((6 ,self.LSR_display_data_num) ,np.nan) # AcclX,Y,Z ,geclo X ,Y,Z
        
        # Spike threshold auto update buffer
        self.calcST_counter = [0 for _ in range(self.spike_channel_num)]
        self.computedST = [0 for _ in range(self.spike_channel_num)]
        self.updateSTflag = [0 for _ in range(self.spike_channel_num)]

        """ build  widgets containing these charts """
        pg.setConfigOption('background', '#666666')
        pg.setConfigOption('foreground', 'w')
        
        """ raw data graph spike mode 1"""
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
        
        """ LFP graph """
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
        self.LFP_pI_channel.getAxis("left").setLabel('LFP', color='#FFC0CB')
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
  
        """ spiking rate and raster graph """
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
        
        """ other sensors graph """
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
        self.accl_pI_channel.getAxis("left").setLabel('accl', color='#FFC0CB')
        self.accl_pI_channel.addLegend()
        
        self.IMU_accl_channel = [] ## accle 3-axis lines
        for i in range(3):
            self.IMU_accl_channel.append(pg.PlotCurveItem(None, None,pen=self.colorList[i] ,name=self.IMUaccle_name[i]))
            self.accl_v1_channel.addItem(self.IMU_accl_channel[i])
        
        self.accle_updating_indicater = pg.InfiniteLine(movable=False, label='{value:0.2f}', angle=90, pen=pg.mkPen(color='r', width=1), 
                                  labelOpts={'position':0.9, 'color':(150,0,0), 'fill': (200,200,200,50)})
        self.accl_v1_channel.addItem(self.accle_updating_indicater)
        
        self.accl_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        self.accl_v1_channel.setXRange(0 ,self.LSR_display_data_num) 
        self.accl_v1_channel.setYRange(-100 ,65535)
        
        # Gryo 3-axis
        self.gryo_view_channel = pg.ViewBox() # 定义一个视图框
        self.gryo_channel = pg.GraphicsView() # 设置 绘图
        self.gryo_channel.setWindowTitle('gryo data 0-15 channels')
        self.gryo_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.gryo_channel.setCentralWidget(self.gryo_layout_channel) # 将绘图区域设置为视图的中心组件
        self.gryo_pI_channel = pg.PlotItem() # 定义图层
        self.gryo_v1_channel = self.gryo_pI_channel.vb # 得到曲线的视图层
        self.gryo_layout_channel.addItem(self.gryo_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.gryo_layout_channel.scene().addItem(self.gryo_view_channel)
        self.gryo_view_channel.setXLink(self.gryo_v1_channel)
        self.gryo_pI_channel.getAxis("left").setLabel('gryo', color='#FFC0CB')
        self.gryo_pI_channel.addLegend()
        
        self.IMU_gryo_channel = [] # Gryo 3-axis lines
        for i in range(3):
            self.IMU_gryo_channel.append(pg.PlotCurveItem(None, None,pen=self.colorList[i] ,name=self.IMUgryo_name[i] ,symbol='o'))
            self.gryo_v1_channel.addItem(self.IMU_gryo_channel[i])
        self.gryo_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        self.gryo_v1_channel.setYRange(-100 ,100)
        self.gryo_v1_channel.setLimits(xMin=0, xMax=self.LSR_display_data_num, yMin=-1000, yMax=5000) # 1mv range
        
        # battery RSOC
        self.RSOC_view_channel = pg.ViewBox() # 定义一个视图框
        self.RSOC_channel = pg.GraphicsView() # 设置 绘图
        self.RSOC_channel.setWindowTitle('RSOC data 0-15 channels')
        self.RSOC_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.RSOC_channel.setCentralWidget(self.RSOC_layout_channel) # 将绘图区域设置为视图的中心组件
        self.RSOC_pI_channel = pg.PlotItem() # 定义一条曲线
        self.RSOC_v1_channel = self.RSOC_pI_channel.vb # 得到曲线的视图层
        self.RSOC_layout_channel.addItem(self.RSOC_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.RSOC_layout_channel.scene().addItem(self.RSOC_view_channel)
        self.RSOC_view_channel.setXLink(self.RSOC_v1_channel)
        self.RSOC_pI_channel.getAxis("left").setLabel('RSOC', color='#FFC0CB')

        self.battery_RSOC_channel = pg.PlotCurveItem(None, None,pen='#FFFFFF') # battery RSOC lines
        self.RSOC_v1_channel.addItem(self.battery_RSOC_channel)
        self.RSOC_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        
        # battery temp
        self.Btemp_view_channel = pg.ViewBox() # 定义一个视图框
        self.Btemp_channel = pg.GraphicsView() # 设置 绘图
        self.Btemp_channel.setWindowTitle('Btemp data 0-15 channels')
        self.Btemp_layout_channel = pg.GraphicsLayout() # 整个绘图layout 初始化
        self.Btemp_channel.setCentralWidget(self.Btemp_layout_channel) # 将绘图区域设置为视图的中心组件
        self.Btemp_pI_channel = pg.PlotItem() # 定义一条曲线
        self.Btemp_v1_channel = self.Btemp_pI_channel.vb # 得到曲线的视图层
        self.Btemp_layout_channel.addItem(self.Btemp_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.Btemp_layout_channel.scene().addItem(self.Btemp_view_channel)
        self.Btemp_view_channel.setXLink(self.Btemp_v1_channel)
        self.Btemp_pI_channel.getAxis("left").setLabel('Btemp', color='#FFC0CB')

        self.battery_Btemp_channel = pg.PlotCurveItem(None, None,pen='#FFFFFF') # battery temp line
        self.Btemp_v1_channel.addItem(self.battery_Btemp_channel)
        self.Btemp_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        
        """ addWidget """
        self.verticalLayout_3.addWidget(self.spike_channel)
        self.horizontalLayout_2.addWidget(self.LFP_channel)
        self.verticalLayout_2.addWidget(self.SR_channel)
        self.verticalLayout.addWidget(self.accl_channel)
        self.verticalLayout.addWidget(self.gryo_channel)
        self.verticalLayout.addWidget(self.RSOC_channel)
        self.verticalLayout.addWidget(self.Btemp_channel)

        """ widget button """
        self.pushButtonList = [self.pushButton ,self.pushButton_2 ,self.pushButton_3 , self.pushButton_4 ,self.pushButton_5 , 
                               self.pushButton_6 ,self.pushButton_7 ,self.pushButton_8 ,self.pushButton_9 ,self.pushButton_10 ,
                               self.pushButton_11 ,self.pushButton_12 ,self.pushButton_13]
        """ combo box """
        self.comboBoxList = [self.comboBox ,self.comboBox_2 ,self.comboBox_3 ,self.comboBox_4] 
        """ line edit """
        self.lineEditList = [self.lineEdit ,self.lineEdit_2 ,self.lineEdit_3]

        QMetaObject.connectSlotsByName(self.MainWindow)

        """call back function connection"""
        # pushButton callback
        for j in range(13): # 13 pushButton
            self.pushButtonList[j].clicked.connect(lambda:self.pushButton_callback(self.centralwidget.sender().text()))
        
        """init commands sending"""
        self.init_wireless_recording()
        self.MainWindow.closeEvent = self.closeEvent

        """real-time data updating"""
        # self.timer = QTimer()
        # self.timer.setInterval(self.guiTimer) #per 10ms check the real time display threshold 
        # self.timer.timeout.connect(self.update_plot_data)
        # self.timer.start()
        
        # self.updateViews()

    # def updateViews(self):
    #     self.spikev2_channel.setGeometry(self.v1_channel.sceneBoundingRect())
            
    # data update function
    def update_plot_data(self, data):  # 注意：实际的一次更新得到的包的数量是在浮动的根据线程处理的速度
        if self.curr_active_ports is not None:
            self.system_data_update(self.curr_active_ports) # TODO update system params like sample rate...
            self.raw_data_generator(self.curr_active_ports, data)
            
            if(int(data[0][0]) == 0):
                """ LFP raw data update """
                # # update infinited line
                self.updating_indicater.setPos(self.ring_lfp_pointer) # span (0, 1)
                self.updating_indicater.label.setFormat('loss_packets:{}/{}'.format(self.lfpmisspackets, self.lfpaccumulpackets))
                for i in range(16): # diff color diff channels separate_interval
                    # update data
                    """ upper and lower band """
                    self.LFP_raw_channel[i].setData(self.LFP_x, self.LFP_raw_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1}))   
            
            elif(int(data[0][0]) == 1):
                """ spike data mode 1 """ 
                #### raw data update
                # update indicte line
                self.spike_updating_indicater_mode_1.setPos(self.ring_spike_pointer)
                self.spike_updating_indicater_mode_1.label.setFormat('loss: {}/{} time: {} s'.format(self.spikemisspackets_mode_1, self.spikeaccumulpackets_mode_1, self.spike_timestamp_note // 1000))
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
                        self.comboBoxList[3].setCurrentText(str(self.channel_panding))
                        # update the threshold
                        self.pushButton_callback('Channel')
                        self.channel_panding += 1
                        if(self.channel_panding >= 16):
                            self.Auto_ST_Update = False
                            self.channel_panding = 0
                            self.Auto_ST_Update_flag = 0
                            self.textBrowser.append("Note:Auto Spike Threshold completed!")
                           

            """ LSR data update """ 
            self.accle_updating_indicater.setPos(self.ring_LSR_pointer) # span (0, 1)
            if(self.ring_LSR_pointer >= self.LSR_display_data_num):
                self.ring_LSR_pointer = 0
            # IMU data
            for imu_channel in range(3):
                self.IMU_accl_channel[imu_channel].setData(self.LSR_timestamp ,self.IMUdata[imu_channel] ,name=self.IMUaccle_name[imu_channel] ,
                                                 pen=pg.mkPen({'color': self.colorList[imu_channel] ,'width':1}),symbol='o')
                self.IMU_gryo_channel[imu_channel].setData(self.LSR_timestamp ,self.IMUdata[imu_channel + 3] ,name=self.IMUgryo_name[imu_channel] ,
                                                 pen=pg.mkPen({'color': self.colorList[imu_channel] ,'width':1}),symbol='o')
            
            # # battery data
            # self.battery_RSOC_channel.setData(self.LSR_timestamp ,self.IMUdata[imu_channel] ,name=self.IMUaccle_name[imu_channel] ,
            #                                      pen=pg.mkPen({'color': self.colorList[imu_channel] ,'width':1}),symbol='o')
             
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
                temp_loss = np.argwhere((temp_loss > self.mSerial[port].LFP_max_interval) | (temp_loss <= 0)).flatten()
                loss_packets_value = len(temp_loss)  #  self.mSerial[port].LFP_max_interval - 1)  lossed number of packets
                self.lfpmisspackets +=  loss_packets_value
                self.lfpaccumulpackets += len(lfp_timestamp)

                # 每save file一次就重新统计丢失的包的数量
                if(self.lfpaccumulpackets >= self.mSerial[port].file_size):
                    self.lfpaccumulpackets = 0
                    self.lfpmisspackets = 0

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
                temp_loss = np.argwhere((temp_loss > self.mSerial[port].Spike_max_interval) | (temp_loss <= 0)).flatten()
                loss_packets_value = len(temp_loss)
                self.spikemisspackets_mode_1 +=  loss_packets_value
                self.spikeaccumulpackets_mode_1 += len(spike_timestamp_mode_1)
                # 每save file一次就重新统计丢失的包的数量
                if(self.spikeaccumulpackets_mode_1 >= self.mSerial[port].file_size):
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


            """ sensing data 9 data """
            sensors_data = np.array(data[3])
            sensor_end_point = self.ring_LSR_pointer + len(sensors_data[0])
            if(sensor_end_point > self.LSR_display_data_num):
                temp_onset = sensor_end_point - self.LSR_display_data_num
                for i in range(6):
                    self.IMUdata[i][self.ring_LSR_pointer:] = sensors_data[i][0:-temp_onset]
                    self.IMUdata[i][0:temp_onset] = sensors_data[i][-temp_onset:]
                self.ring_LSR_pointer = temp_onset
            else:
                for i in range(6):
                    self.IMUdata[i][self.ring_LSR_pointer:sensor_end_point] = sensors_data[i]
                self.ring_LSR_pointer = sensor_end_point

    
    def system_data_update(self ,port):
        """
        acquire timestamp and other system parameters
        """
        pass

    def init_wireless_recording(self):
        # self.curr_channel = self.comboBox[3].currentIndex()
        self.pushButton_callback(u"read COM list") 
        pass
    

    """callback function"""
    @QtCore.pyqtSlot()
    def pushButton_callback(self ,button_text):
        self.my_sender = button_text
        
        if self.my_sender == u"open serial":
            # open serial port and save data
            if self.comboBoxList[0].currentIndex() not in self.mSerial_disable:
                # start read data from Serial
                self.mSerial[self.comboBoxList[0].currentIndex()] = SerialPort(self.comboBoxList[0].currentText(),2000000)
                self.mSerial[self.comboBoxList[0].currentIndex()].port_open()
                self.mSerial[self.comboBoxList[0].currentIndex()].GUIUpdate.connect(self.update_plot_data)
                self.mSerial[self.comboBoxList[0].currentIndex()].start()

                self.mSerial_disable.append(self.comboBoxList[0].currentIndex()) # 目前是打开了这个port就不能关闭
                self.curr_active_ports = self.comboBoxList[0].currentIndex()
                # 注意，每次显示的都只有当前选定的port的data ,注意com port 必须为 数据上发的port，不能是其他的port
            pass
        
        elif self.my_sender == u"upper cutoff":
            pass
        
        elif self.my_sender == u"lower cutoff":
            pass

        elif self.my_sender == u"template upload":
            pass
        
        elif self.my_sender == u"open data file":
            os.system("start explorer D:\\python\\Wireless_Nerual_Signal_Recording\\UI\\Qt based UI\\spike_data")
            pass
        
        elif self.my_sender == u"show the units waveform":
            pass

        elif self.my_sender == u"Mode switch":
            # switch sample mode
            if self.curr_active_ports in self.mSerial_disable:
                try:
                    mode = int(self.lineEdit.text())
                except:
                    mode = 4 # invalid mode
                if(mode < 3):
                    self.err = self.mSerial[self.curr_active_ports].send_data([0x02 ,0x00, int(hex(mode) ,16), 0x00])
            else:
                QMessageBox.warning(self.MainWindow, "Warning", "Please opening the Serial port !")
            pass
        
        elif self.my_sender == u"sample switch on":
            if self.curr_active_ports in self.mSerial_disable:
                # clear the buffer
                self.mSerial[self.curr_active_ports].flush()
                self.open_command = [0x01 ,0x00] 
                self.err = self.mSerial[self.curr_active_ports].send_data(self.open_command)
            else:
                QMessageBox.warning(self.MainWindow, "Warning", "Please opening the Serial port !")
            pass
        
        elif self.my_sender == u"sample switch off":
            if self.curr_active_ports in self.mSerial_disable:
                self.close_command = [0x02 ,0x00, 0xff, 0x00] # invalid sample mode
                self.err = self.mSerial[self.curr_active_ports].send_data(self.close_command)
            else:
                QMessageBox.warning(self.MainWindow, "Warning", "Please opening the Serial port !")
            pass
        
        elif self.my_sender == u"Channel": # for mode 1
            if self.curr_active_ports in self.mSerial_disable:
                self.channel_command = [0x00, 0x04 ,  0x00 ,0x00,    0x00, 0x00] 
                # recording raw channel
                self.channel_command[-4] = int(hex(self.comboBoxList[3].currentIndex()) ,16)
                # TODO threshold; 注意这里需要等待 改通道的数据全部刷新完成后再使用 
                temp_threshold = self.mSerial[self.curr_active_ports].calc_SpikeThreshold(self.spike_raw_data[0])
                temp_threshold = int((temp_threshold / 1000 / 1000 * 192 + 1.225) / self.mSerial[self.curr_active_ports].DAC_resolution)
                temp_threshold = temp_threshold - int('0x8000', 16)
                if(temp_threshold >= int('0x8000', 16)):
                    temp_threshold = 0
                    self.textBrowser.append("Error:Auto Spike Threshold overflow!")
                self.textBrowser.append("Threshold update: channel {} threshold {}".format(self.spike_raw_channel, temp_threshold))

                temp_threshold = hex(temp_threshold).replace('0x' ,'').zfill(4)
                self.channel_command[-1] = int(temp_threshold[0:2] ,16)
                self.channel_command[-2] = int(temp_threshold[2:4] ,16)

                self.err = self.mSerial[self.curr_active_ports].send_data(self.channel_command)
            else:
                QMessageBox.warning(self.MainWindow, "Warning", "Please opening the Serial port !")
        
        elif self.my_sender == u"threshold set":
            if self.curr_active_ports in self.mSerial_disable:
               pass
            else:
                QMessageBox.warning(self.MainWindow, "Warning", "Please opening the Serial port !")
            pass
        
        elif self.my_sender == u"auto ST update":
            if self.curr_active_ports in self.mSerial_disable:
                self.Auto_ST_Update = True
                self.channel_panding = 0
                self.Auto_ST_Update_flag = 0
                self.textBrowser.append("Note:Auto Spike Threshold begining!")
            else:
                QMessageBox.warning(self.MainWindow, "Warning", "Please opening the Serial port !")
            pass
        
        elif self.my_sender == u"MT threshold set":
            if self.curr_active_ports in self.mSerial_disable:
                self.MT_threshold = [0x13 ,0x00 ,0x00 ,0x00]
                self.MT_threshold[-1] = int(self.lineEdit_3.text(),16) #同上
                self.err = self.mSerial[self.curr_active_ports].send_data(self.MT_threshold)
            else:
                QMessageBox.warning(self.MainWindow, "Warning", "Please opening the Serial port !")
            pass
        
        elif self.my_sender == u"read COM list":
            self.comboBoxList[0].clear()
            port_list = list(serial.tools.list_ports.comports())
            self.com_num = len(port_list)
            self.port_list_name = []
            if self.com_num <= 0:
                QMessageBox.warning(self.MainWindow, "Warning", "cannot find available COM port!")
            else:
                for each_port in port_list:
                    self.port_list_name.append(each_port[0])
                for _ in range(self.com_num):
                    self.comboBoxList[0].addItem("")
                for index ,i in enumerate(self.port_list_name):
                    self.comboBoxList[0].setItemText(index, QCoreApplication.translate("MainWindow", u"{}".format(i), None))


    def closeEvent(self, event): 
        reply = QMessageBox.question(self.MainWindow, 'Message',"Are you sure to quit?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No )

        if reply == QMessageBox.StandardButton.Yes:
            #TODO thread quit and sample stop and so on...
            event.accept()
        else:
            event.ignore()



def show_mainwindow():
    app = QtWidgets.QApplication(sys.argv)
    main_win = ESBMainWindow()
    main_win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    #pg.exec()
    show_mainwindow()
    

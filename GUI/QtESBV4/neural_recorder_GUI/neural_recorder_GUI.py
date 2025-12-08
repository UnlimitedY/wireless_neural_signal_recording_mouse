from PyQt6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
    QLineEdit, QMainWindow, QMenuBar, QPushButton,
    QSizePolicy, QSpinBox, QStatusBar, QTextBrowser,
    QVBoxLayout, QWidget ,QMessageBox, QDialog)
from PyQt6.QtGui import QFont
# 在文件开头的导入部分添加
from scipy import signal
from scipy.fft import fft, fftfreq
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton
from PyQt6.QtCore import QTimer

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


# 添加新的LFP频谱窗口类
class LFPSpectrumWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("LFP Spectrum Analysis")
        self.setGeometry(100, 100, 1000, 700)
        
        # 采样率设置
        self.fs = 1250  # 1250Hz采样率
        self.channels = 16  # 16个LFP通道
        
        # 频率范围设置
        self.freq_min = 0
        self.freq_max = 625
        
        # 创建中心部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 创建控制面板
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # 创建pyqtgraph图形显示区域
        self.plot_widget = pg.PlotWidget()
        
        # 设置坐标轴标签和样式
        self.plot_widget.setLabel('left', 'Power Spectral Density', units='dB')
        self.plot_widget.setLabel('bottom', 'Frequency', units='Hz')
        self.plot_widget.setTitle('LFP Spectrum Analysis - 16 Channels')
        
        # 显示网格和坐标轴
        self.plot_widget.showGrid(True, True, alpha=0.3)
        
        # 设置背景颜色（使用深色背景以便看清坐标轴）
        self.plot_widget.setBackground('k')  # 黑色背景
        
        # 获取坐标轴并设置样式
        bottom_axis = self.plot_widget.getAxis('bottom')
        left_axis = self.plot_widget.getAxis('left')
        
        # 设置坐标轴文字颜色和大小
        bottom_axis.setTextPen('w')  # 白色文字
        left_axis.setTextPen('w')    # 白色文字
        
        # 设置坐标轴刻度样式
        bottom_axis.setPen('w')      # 白色坐标轴线
        left_axis.setPen('w')        # 白色坐标轴线
        
        # 强制显示坐标轴刻度
        bottom_axis.setStyle(tickTextOffset=10, tickLength=10)
        left_axis.setStyle(tickTextOffset=10, tickLength=10)
        
        # 设置频率范围
        self.plot_widget.setXRange(self.freq_min, self.freq_max)
        
        # 设置合理的Y轴范围
        self.plot_widget.setYRange(-100, 50)  # dB范围
        
        # 添加图例
        self.plot_widget.addLegend()
        
        layout.addWidget(self.plot_widget)
        
        # 初始化频谱曲线
        self.init_spectrum_curves()
        
        # 定时器用于更新频谱
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_spectrum)
        self.update_timer.start(500)  # 每500ms更新一次
        
    def create_control_panel(self):
        """Create control panel"""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        
        # Frequency range selection
        freq_label = QLabel("Frequency Range:")
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["0-625Hz", "0-100Hz", "0-50Hz", "1-100Hz", "10-100Hz", "0-250Hz"])
        self.freq_combo.currentTextChanged.connect(self.update_frequency_range)
        
        # Display mode selection
        mode_label = QLabel("Display Mode:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["All Channels", "Average Power Spectrum", "Select Channel"])
        self.mode_combo.currentTextChanged.connect(self.update_display_mode)
        
        # Window function selection
        window_label = QLabel("Window Function:")
        self.window_combo = QComboBox()
        self.window_combo.addItems(["hann", "hamming", "blackman", "bartlett"])
        
        # Channel selection (used when "Select Channel" mode is chosen)
        channel_label = QLabel("Select Channel:")
        self.channel_combo = QComboBox()
        self.channel_combo.addItems([f"Channel {i}" for i in range(16)])
        self.channel_combo.setEnabled(False)
        
        layout.addWidget(freq_label)
        layout.addWidget(self.freq_combo)
        layout.addWidget(mode_label)
        layout.addWidget(self.mode_combo)
        layout.addWidget(window_label)
        layout.addWidget(self.window_combo)
        layout.addWidget(channel_label)
        layout.addWidget(self.channel_combo)
        layout.addStretch()
        
        return panel
    
    def init_spectrum_curves(self):
        """初始化频谱曲线"""
        self.spectrum_curves = []
        
        # 为16个通道创建不同颜色的曲线
        colors = [
            '#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF', '#00FFFF',
            '#800000', '#008000', '#000080', '#808000', '#800080', '#008080',
            '#FFA500', '#A52A2A', '#DDA0DD', '#98FB98', '#F0E68C', '#DEB887',
            '#5F9EA0', '#7FFF00', '#D2691E', '#FF7F50', '#6495ED', '#DC143C',
            '#00CED1', '#9400D3', '#FF1493', '#00BFFF', '#696969', '#1E90FF',
            '#B22222', '#228B22'
        ]
        
        for i in range(16):
            # 创建曲线，初始时不显示数据
            curve = self.plot_widget.plot(
                [], [], 
                pen=pg.mkPen(color=colors[i], width=1.5),
                name=f'Ch{i}'
            )
            self.spectrum_curves.append(curve)
    
    def update_frequency_range(self, freq_range):
        """更新频率范围"""
        if freq_range == "0-500Hz":
            self.freq_min, self.freq_max = 0, 500
        elif freq_range == "0-250Hz":
            self.freq_min, self.freq_max = 0, 250
        elif freq_range == "0-100Hz":
            self.freq_min, self.freq_max = 0, 100
        elif freq_range == "0-50Hz":
            self.freq_min, self.freq_max = 0, 50
        elif freq_range == "1-100Hz":
            self.freq_min, self.freq_max = 1, 100
        elif freq_range == "10-100Hz":
            self.freq_min, self.freq_max = 10, 100
        
        # 更新图的X轴范围
        self.plot_widget.setXRange(self.freq_min, self.freq_max)
    
    def update_display_mode(self, mode):
        """Update display mode"""
        if mode == "Select Channel":
            self.channel_combo.setEnabled(True)
            # Hide all curves
            for curve in self.spectrum_curves:
                curve.setData([], [])
        else:
            self.channel_combo.setEnabled(False)
    
    def update_spectrum(self):
        """更新频谱显示"""
        if self.parent is None or not hasattr(self.parent, 'LFP_raw_data'):
            return
        
        try:
            current_mode = self.mode_combo.currentText()
            window_func = self.window_combo.currentText()
            
            if current_mode == "Average Power Spectrum":
                self.update_average_spectrum(window_func)
            elif current_mode == "Select Channel":
                self.update_selected_channel_spectrum(window_func)
            else:  # All Channels
                self.update_all_channels_spectrum(window_func)
                
        except Exception as e:
            print(f"频谱更新错误: {e}")
    
    def update_all_channels_spectrum(self, window_func):
        """更新所有通道频谱"""
        for ch in range(16):
            # 获取通道数据（去除偏移）
            channel_data = self.parent.LFP_raw_data[ch] - ch * self.parent.separate_interval
            
            # 去除NaN值
            valid_data = channel_data[~np.isnan(channel_data)]
            
            if len(valid_data) > 256:  # 确保有足够的数据点
                # 计算功率谱密度
                f, Pxx = signal.welch(valid_data, self.fs, 
                                    window=window_func, 
                                    nperseg=min(1024, len(valid_data)//4),
                                    noverlap=None)
                
                # 转换为dB
                Pxx_db = 10 * np.log10(Pxx + 1e-12)  # 避免log(0)
                
                # 频率范围过滤
                freq_mask = (f >= self.freq_min) & (f <= self.freq_max)
                
                # 更新曲线
                self.spectrum_curves[ch].setData(f[freq_mask], Pxx_db[freq_mask])
            else:
                # 如果数据不足，清空曲线
                self.spectrum_curves[ch].setData([], [])
    
    def update_average_spectrum(self, window_func):
        """更新平均功率谱"""
        # 先隐藏所有单独的通道曲线
        for i, curve in enumerate(self.spectrum_curves):
            if i > 0:  # 保留第一条曲线用于显示平均值
                curve.setData([], [])
        
        all_pxx = []
        
        for ch in range(16):
            # 获取通道数据（去除偏移）
            channel_data = self.parent.LFP_raw_data[ch] - ch * self.parent.separate_interval
            valid_data = channel_data[~np.isnan(channel_data)]
            
            if len(valid_data) > 256:
                f, Pxx = signal.welch(valid_data, self.fs, 
                                    window=window_func, 
                                    nperseg=min(1024, len(valid_data)//4))
                all_pxx.append(Pxx)
        
        if all_pxx:
            # 计算平均功率谱
            avg_pxx = np.mean(all_pxx, axis=0)
            avg_pxx_db = 10 * np.log10(avg_pxx + 1e-12)
            
            # 频率范围过滤
            freq_mask = (f >= self.freq_min) & (f <= self.freq_max)
            
            # 使用第一条曲线显示平均频谱，并修改其样式
            self.spectrum_curves[0].setData(f[freq_mask], avg_pxx_db[freq_mask])
            self.spectrum_curves[0].setPen(pg.mkPen(color='red', width=3))
    
    def update_selected_channel_spectrum(self, window_func):
        """更新选择的通道频谱"""
        selected_ch = self.channel_combo.currentIndex()
        
        # 隐藏所有曲线
        for curve in self.spectrum_curves:
            curve.setData([], [])
        
        # 获取选择通道的数据
        channel_data = self.parent.LFP_raw_data[selected_ch] - selected_ch * self.parent.separate_interval
        valid_data = channel_data[~np.isnan(channel_data)]
        
        if len(valid_data) > 256:
            # 计算功率谱密度
            f, Pxx = signal.welch(valid_data, self.fs, 
                                window=window_func, 
                                nperseg=min(1024, len(valid_data)//4))
            
            # 转换为dB
            Pxx_db = 10 * np.log10(Pxx + 1e-12)
            
            # 频率范围过滤
            freq_mask = (f >= self.freq_min) & (f <= self.freq_max)
            
            # 显示选择的通道
            self.spectrum_curves[selected_ch].setData(f[freq_mask], Pxx_db[freq_mask])
            self.spectrum_curves[selected_ch].setPen(pg.mkPen(color='blue', width=2))


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
                          '#ffffff', '#42d4f4', '#e6194B', '#3cb44b', '#ffe119', '#4363d8', 
                          '#f58231', '#42d4f4', '#f032e6', '#fabed4', 
                          '#469990', '#dcbeff', '#9A6324', '#fffac8', 
                          '#800000', '#aaffc3', '#000075', '#a9a9a9', 
                          '#ffffff', '#42d4f4'] # pink cyan red
        self.IMUaccle_name = ['Accl_X' ,'Accl_Y' ,'Accl_Z']
        self.IMUgryo_name  = ['Gryo_X' ,'Gryo_Y' ,'Gryo_Z']

        self.current_sample_mode = 0 

        """ init params """
        # system
        self.mSerial = None
        self.t1 = None
        self.curr_active_ports = None
        self.pen1 = pg.mkPen(color=(255, 0, 0))
        # RF power control - 使用主UI中的串口连接
        self.rf_power_status = 1  # 1: 关闭, 2: 开启
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
        self.lfp_channel_num = 16
        
        ################# spike raw data mode 1
        self.ring_spike_pointer = 0
        self.spike_x = np.arange(0, self.spike_display_data_num, 1)
        self.spike_raw_data = np.full((1 ,self.spike_display_data_num) ,np.nan)
        # Spike滤波相关参数与缓冲
        self.spike_filter_enabled = False
        self.spike_filter_low_cut = 300.0
        self.spike_filter_high_cut = 3000.0
        self.spike_filter_fs = 20000.0
        self.spike_filtered_data = np.full((1 ,self.spike_display_data_num) ,np.nan)
        self._spike_filter_b = None
        self._spike_filter_a = None
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
        self.separate_interval = 500# 500 
        self.ring_lfp_pointer = 0
        self.LFP_x = np.arange(0, self.lfp_display_data_num, 1)
        self.LFP_raw_data =np.full((self.lfp_channel_num ,self.lfp_display_data_num) ,np.nan) 
        self.lfpmisspackets = 0 # recording the number of missed packets every GUI update events
        self.lfpaccumulpackets = 0 # recording received packets number

        self.lfp_filter_length = self.lfp_sample_rate * 2 # 2s data length
        self.lfp_filter_buffer = np.full((self.lfp_channel_num ,self.lfp_filter_length) ,np.nan)

        ################# ESA raw data (same format as LFP)
        self.esa_channel_num = 16
        self.ring_esa_pointer = 0
        self.ESA_x = np.arange(0, self.lfp_display_data_num, 1)  # 使用与LFP相同的时间轴
        self.ESA_raw_data = np.full((self.esa_channel_num, self.lfp_display_data_num), np.nan)

        ################# spike mode 2 
        self.separate_interval_spike = 500
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
        self.RSOC_stat = np.full((1 ,self.LSR_display_data_num) ,np.nan) # battery charging status
        self.STAT_stat = np.full((1 ,self.LSR_display_data_num) ,np.nan) # battery_PPM
        self.Voltage_stat = np.full((1 ,self.LSR_display_data_num) ,np.nan) # Power status
        self.IMUdata = np.full((6 ,self.LSR_display_data_num) ,np.nan) # AcclX,Y,Z ,geclo X ,Y,Z

        # current battery status
        self.RSOC = 0
        self.Battery_STAT = 0
        self.Battery_voltage = 0
        self.RF_turnoff = False

        self.RF_timer = QTimer()
        self.RF_timer.timeout.connect(self.rf_power_control)
        self.RF_timer.start(1000 * 60 * 10)  # 每500ms更新一次
        
        # 连接RF按钮信号
        self.rf_power_on_button.clicked.connect(self.rf_power_on)
        self.rf_power_off_button.clicked.connect(self.rf_power_off)
        
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
        self.LFP_pI_channel.setTitle('LFP data 16 channels')
        self.LFP_v1_channel = self.LFP_pI_channel.vb # 得到曲线的视图层
        self.LFP_layout_channel.addItem(self.LFP_pI_channel, row = 1, col = 1)# 将这个曲线层放到中间
        self.LFP_layout_channel.scene().addItem(self.LFP_view_channel)
        self.LFP_view_channel.setXLink(self.LFP_v1_channel)
        self.LFP_pI_channel.getAxis("left").setLabel('LFP 1kHz', color='#FFC0CB')
        self.LFP_pI_channel.addLegend()
         
        # LFP and ESA lines (32 channels total: 16 LFP + 16 ESA, alternating)
        self.LFP_raw_channel = []
        self.ESA_raw_channel = []
        
        # 创建32个通道：LFP和ESA交替显示
        for i in range(self.lfp_channel_num):
            # LFP通道 (偶数位置: 0, 2, 4, ...)
            lfp_channel = pg.PlotCurveItem(None, None, pen='#FFFFFF')
            self.LFP_raw_channel.append(lfp_channel)
            self.LFP_v1_channel.addItem(lfp_channel)
            
            # ESA通道 (奇数位置: 1, 3, 5, ...)
            esa_channel = pg.PlotCurveItem(None, None, pen='#FFFF00')  # 黄色用于ESA
            self.ESA_raw_channel.append(esa_channel)
            self.LFP_v1_channel.addItem(esa_channel)
            
        # updating indicate lines: infiniteLine  
        self.updating_indicater = pg.InfiniteLine(movable=False, label='', angle=90, pen=pg.mkPen(color='w', width=3), 
                                  labelOpts={'position':0.99, 'color':'y', 'fill': (200,200,200,50)})
        self.LFP_v1_channel.addItem(self.updating_indicater)
        
        # 更新ticks设置，显示32个通道（LFP和ESA交替）
        combined_ticks = {}
        for channel in range(16):
            # LFP通道标签 (偶数位置)
            lfp_y_pos = int(channel * 2 * self.separate_interval)
            combined_ticks[lfp_y_pos] = f'LFP{channel}'
            
            # ESA通道标签 (奇数位置)
            esa_y_pos = int((channel * 2 + 1) * self.separate_interval)
            combined_ticks[esa_y_pos] = f'ESA{channel}'
            
        self.LFP_pI_channel.getAxis("left").setTicks([combined_ticks.items()])

        self.LFP_v1_channel.enableAutoRange(axis=pg.ViewBox.XYAxes ,enable = True)
        # 更新Y轴范围以适应32个通道（16个LFP + 16个ESA）
        total_channels = self.lfp_channel_num * 2  # 32个通道
        self.LFP_v1_channel.setLimits(xMin=0, xMax=self.lfp_display_data_num, yMin=-self.separate_interval , yMax=(total_channels + 1) * self.separate_interval)
        self.LFP_v1_channel.setYRange(-self.separate_interval ,(total_channels + 1) * self.separate_interval) 
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

        self.AP_v1_channel.setLimits(xMin=0, xMax=self.spike_display_data_num, yMin=-self.separate_interval_spike, yMax=(self.spike_channel_num + 1) * self.separate_interval_spike)
        self.AP_v1_channel.setYRange(-self.separate_interval_spike ,(self.spike_channel_num + 1) * self.separate_interval_spike) 
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
        # LFP保存按钮（互斥控制）
        self.lfp_tab.start_save_button.clicked.connect(self.start_save_lfp)
        self.lfp_tab.stop_save_button.clicked.connect(self.stop_save_lfp)
        self.lfp_tab.start_save_mode3_button.clicked.connect(self.start_save_mode3)
        self.lfp_tab.stop_save_mode3_button.clicked.connect(self.stop_save_mode3)
        self.spike4ch_tab.start_save_button.clicked.connect(self.start_save_mode2)
        self.spike4ch_tab.stop_save_button.clicked.connect(self.stop_save_mode2)
        self.spike1ch_tab.start_save_button.clicked.connect(self.start_save_mode1)
        self.spike1ch_tab.stop_save_button.clicked.connect(self.stop_save_mode1)

        self.start_sampling_button.clicked.connect(self.sample_start)
        self.stop_sampling_button.clicked.connect(self.sample_stop)
        self.sampling_mode_combo.currentIndexChanged.connect(self.sample_mode_switch)
        self.spike4ch_tab.send_channels_button.clicked.connect(self.spike_channel_switch_mode2)
        self.spike1ch_tab.send_command_button.clicked.connect(self.spike_channel_switch_mode1)
        # Spike1Ch 滤波与频谱控件信号连接
        self.spike1ch_tab.filter_enable_checkbox.toggled.connect(self.on_spike_filter_toggle)
        self.spike1ch_tab.low_cut_spin.valueChanged.connect(self.on_spike_filter_params_changed)
        self.spike1ch_tab.high_cut_spin.valueChanged.connect(self.on_spike_filter_params_changed)
        self.spike1ch_tab.sample_rate_combo.currentIndexChanged.connect(self.on_spike_sample_rate_changed)
        self.spike1ch_tab.open_spectrum_button.clicked.connect(self.open_spike_spectrum)
        self.raster_tab.auto_threshold_button.clicked.connect(self.Auto_threshold_update)
        self.raster_tab.channel_combo.currentIndexChanged.connect(self.spike_threshold_set)
        self.raster_tab.threshold_combo.currentIndexChanged.connect(self.spike_threshold_set)
        self.update_battery_button.clicked.connect(self.IMU_mode_setting)
        # self.lfp_tab.enable_filter_button.clicked.connect(self.lfp_filter_on)
        # self.lfp_tab.disable_filter_button.clicked.connect(self.lfp_filter_off)

        self.rf_power_on_button.clicked.connect(self.rf_power_on)
        self.rf_power_off_button.clicked.connect(self.rf_power_off)

        # Add spectrum window button
        self.spectrum_window_button = QPushButton("LFP Spectrum Analysis")
        self.spectrum_window_button.clicked.connect(self.open_spectrum_window)
        # Add button to LFP tab control panel layout
        self.lfp_tab.control_panel_layout.addWidget(self.spectrum_window_button)
        # Spectrum window instance
        self.spectrum_window = None
    

    def open_spectrum_window(self):
        """Open LFP spectrum analysis window"""
        if self.spectrum_window is None:
            self.spectrum_window = LFPSpectrumWindow(self)
        
        self.spectrum_window.show()
        self.spectrum_window.raise_()
        self.spectrum_window.activateWindow()

    # Spike 单通道滤波相关方法
    def _update_spike_filter_coeffs(self):
        """根据当前参数计算带通滤波器系数（Butterworth）"""
        fs = float(self.spike_filter_fs)
        low = max(1.0, float(self.spike_filter_low_cut))
        high = min(fs/2 - 1.0, float(self.spike_filter_high_cut))
        if high <= low:
            high = low + 1.0
        nyq = fs / 2.0
        wn = [low/nyq, high/nyq]
        try:
            self._spike_filter_b, self._spike_filter_a = signal.butter(4, wn, btype='bandpass')
        except Exception:
            self._spike_filter_b, self._spike_filter_a = None, None

    def _apply_spike_filter_buffer(self):
        """对显示缓冲进行滤波，结果写入 spike_filtered_data"""
        if not self.spike_filter_enabled:
            return
        if self._spike_filter_b is None or self._spike_filter_a is None:
            self._update_spike_filter_coeffs()
            if self._spike_filter_b is None:
                return
        x = np.array(self.spike_raw_data[0], dtype=np.float64)
        nan_mask = np.isnan(x)
        if np.all(nan_mask):
            return
        x[nan_mask] = 0.0
        try:
            y = signal.lfilter(self._spike_filter_b, self._spike_filter_a, x)
        except Exception:
            return
        y[nan_mask] = np.nan
        self.spike_filtered_data[0] = y

    def on_spike_filter_toggle(self, checked):
        self.spike_filter_enabled = bool(checked)
        if self.spike_filter_enabled:
            self._update_spike_filter_coeffs()
            self._apply_spike_filter_buffer()
        # 立即刷新显示
        try:
            if self.spike_filter_enabled:
                self.raw_dataline_channel.setData(self.spike_x, self.spike_filtered_data[0], pen=pg.mkPen({'color': 'c' ,'width':1}))
            else:
                self.raw_dataline_channel.setData(self.spike_x, self.spike_raw_data[0], pen=pg.mkPen({'color': 'w' ,'width':1}))
        except Exception:
            pass

    def on_spike_filter_params_changed(self):
        self.spike_filter_low_cut = float(self.spike1ch_tab.low_cut_spin.value())
        self.spike_filter_high_cut = float(self.spike1ch_tab.high_cut_spin.value())
        if self.spike_filter_enabled:
            self._update_spike_filter_coeffs()
            self._apply_spike_filter_buffer()
            try:
                self.raw_dataline_channel.setData(self.spike_x, self.spike_filtered_data[0], pen=pg.mkPen({'color': 'c' ,'width':1}))
            except Exception:
                pass

    def on_spike_sample_rate_changed(self, idx):
        # 0 -> 12500 Hz ; 1 -> 20000 Hz
        self.spike_filter_fs = 12500.0 if idx == 0 else 20000.0
        if self.spike_filter_enabled:
            self._update_spike_filter_coeffs()
            self._apply_spike_filter_buffer()
            try:
                self.raw_dataline_channel.setData(self.spike_x, self.spike_filtered_data[0], pen=pg.mkPen({'color': 'c' ,'width':1}))
            except Exception:
                pass

    class _SpikeSpectrumDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Spike Spectrum")
            self.resize(800, 400)
            layout = QVBoxLayout(self)
            self.plot_widget = pg.PlotWidget()
            layout.addWidget(self.plot_widget)

    def open_spike_spectrum(self):
        """打开频谱窗口，计算当前显示缓冲的幅度谱"""
        dlg = self._SpikeSpectrumDialog(self)
        x = self.spike_filtered_data[0] if self.spike_filter_enabled else self.spike_raw_data[0]
        try:
            sig = np.array(x, dtype=np.float64)
            sig[np.isnan(sig)] = 0.0
            fs = float(self.spike_filter_fs)
            n = len(sig)
            if n > 1:
                freqs = np.fft.rfftfreq(n, d=1.0/fs)
                spectrum = np.abs(np.fft.rfft(sig))
                dlg.plot_widget.plot(freqs, spectrum, pen=pg.mkPen({'color': 'y', 'width': 2}))
                dlg.plot_widget.setLabel('bottom', 'Frequency', units='Hz')
                dlg.plot_widget.setLabel('left', 'Amplitude')
                dlg.plot_widget.setTitle("Spike Spectrum ({} Hz)".format(int(fs)))
        except Exception:
            pass
        dlg.show()
        dlg.exec()
        
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
                # update LFP data
                for i in range(16): # diff color diff channels separate_interval
                    self.LFP_raw_channel[i].setData(self.LFP_x, self.LFP_raw_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1}))   

                # update ESA data
                for i in range(16): # ESA channels with different colors
                    self.ESA_raw_channel[i].setData(self.ESA_x, self.ESA_raw_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1, "style": QtCore.Qt.PenStyle.DashLine}))  # 使用PyQt6枚举修正虚线样式

                 #### raster data update
                # update infinited line
                self.spike_raster_updating_indicater_mode_1.setPos(self.ring_spike_raster_pointer)
                # update data
                if(np.isnan(self.spike_raster_data).any() == False):
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        for i in range(16): # diff color diff channels separate_interval
                            self.spike_raster_data[i][self.spike_raster_data[i] == 0] = -1
                            self.spike_raster_channel[i].setData(self.spike_raster_x, self.spike_raster_data[i] ,pen=pg.mkPen({'color': self.colorList[i] ,'width':1}))   
                    # update spike rate data
                    self.spike_raster_data[self.spike_raster_data == -1] = 0
                    self.SR_value[0] = my_gaussian_filter1d(np.sum(self.spike_raster_data ,axis=0) ,sigma=10)
                    self.spike_SR_channel.setData(self.spike_raster_x ,self.SR_value[0]  ,pen=pg.mkPen({'color': 'w' ,'width':2}))  # ,fillLevel=10, fillBrush=(255,255,255,30)
            
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
                # update data（按需显示滤波）
                if self.spike_filter_enabled:
                    try:
                        self.raw_dataline_channel.setData(self.spike_x, self.spike_filtered_data[0] ,pen=pg.mkPen({'color': 'c' ,'width':1}))
                    except Exception:
                        pass
                else:
                    self.raw_dataline_channel.setData(self.spike_x, self.spike_raw_data[0] ,pen=pg.mkPen({'color': 'w' ,'width':1}))
 
                #### raster data update
                # update infinited line
                self.spike_raster_updating_indicater_mode_1.setPos(self.ring_spike_raster_pointer)
                # update data
                if(np.isnan(self.spike_raster_data).any() == False):
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
            self.update_battery_indicator(self.RSOC, self.Battery_STAT, self.Battery_voltage)
             
    def raw_data_generator(self ,port, data):
        """
        update all data array via ring buffer
        @data:
        lfp_mode_0: [[0], self.lfptimestamp_GUI, self.lfpdata_GUI, self.sensordata_GUI]
        spike_mode_1: [[1, self.spike_channel_index_mode1], self.spiketimestamp_GUI, self.spikedata_GUI, self.sensordata_GUI, self.spikerasterdata_GUI]
        """
        if port is not None:
            """ Mode 1&3 """
            if(int(data[0][0]) == 0): #TODO LFP re-reference
                """ LFP raw data figure 1"""
                lfp_timestamp = np.array(data[1])
                raw_data = np.array(data[2])
                ESA_raw_data = np.array(data[5]) * 100 # 放缩 到 lfp 一样的尺度
                spike_raster_data_mode_1 = np.array(data[4], dtype=np.float32)
                
                # maz interval between packets
                Interval_packets_max = 0
                if(self.current_sample_mode == 0):
                    Interval_packets_max = self.mSerial.LFP_max_interval
                elif(self.current_sample_mode == 3):
                    Interval_packets_max = self.mSerial.mode3_max_interval

                # statitic dropped packets
                temp_loss = np.diff(lfp_timestamp) 
                temp_loss = temp_loss[(temp_loss > Interval_packets_max) | (temp_loss <= 0)]
                loss_packets_value = len(temp_loss // (Interval_packets_max - 1))
                # if(loss_packets_value > 0):
                #     print("LFP data moide3:", Interval_packets_max, loss_packets_value)
                self.lfpmisspackets +=  loss_packets_value
                self.lfpaccumulpackets += len(lfp_timestamp)
                # 每save file 10次就重新统计丢失的包的数量
                if(self.lfpaccumulpackets >= (self.mSerial.file_size_lfp) * 10):
                    self.lfpaccumulpackets = 0
                    self.lfpmisspackets = 0

                # update figure data
                endpoint = self.ring_lfp_pointer + len(raw_data[0])
                # for ESA update pointer
                ESA_pointer_temp = self.ring_lfp_pointer
                if(endpoint > self.lfp_display_data_num):
                    temp_onset = endpoint - self.lfp_display_data_num
                    for channel_num in range(16):
                        # LFP通道使用偶数位置的Y轴偏移 (channel_num * 2)
                        temp_vdd = raw_data[channel_num] + (channel_num * 2) * self.separate_interval
                        self.LFP_raw_data[channel_num][self.ring_lfp_pointer:] = temp_vdd[0:-temp_onset]
                        self.LFP_raw_data[channel_num][0:temp_onset] = temp_vdd[-temp_onset:]
                    self.ring_lfp_pointer = temp_onset
                else:
                    for channel_num in range(16):
                        # LFP通道使用偶数位置的Y轴偏移 (channel_num * 2)
                        self.LFP_raw_data[channel_num][self.ring_lfp_pointer:endpoint] = raw_data[channel_num] + (channel_num * 2) * self.separate_interval
                    self.ring_lfp_pointer = endpoint # update indicater

                # filter 只滤波pointer 之前的所有数据
                if(not self.lfp_tab.enable_filter_button.isEnabled() and self.ring_lfp_pointer > 0):
                    for channel_num in range(16):
                        # LFP通道使用偶数位置的Y轴偏移 (channel_num * 2)
                        self.LFP_raw_data[channel_num][0:self.ring_lfp_pointer] = LFP_filter(self.LFP_raw_data[channel_num][0:self.ring_lfp_pointer] - (channel_num * 2) * self.separate_interval, 
                                                                                             self.lfp_tab.low_cutoff.currentText(), self.lfp_tab.high_cutoff.currentText()) + (channel_num * 2) * self.separate_interval

                # ESA数据处理 (与LFP数据处理逻辑相同，但使用不同的Y轴偏移
                # 更新ESA图表数据 (使用与LFP相同的ring pointer)
                if(len(ESA_raw_data[0]) != 0):
                    if(endpoint > self.lfp_display_data_num ):
                        temp_onset = endpoint - self.lfp_display_data_num
                        for channel_num in range(16):
                            # ESA通道使用奇数位置的Y轴偏移 (channel_num * 2 + 1)
                            temp_vdd = ESA_raw_data[channel_num] + (channel_num * 2 + 1) * self.separate_interval
                            self.ESA_raw_data[channel_num][ESA_pointer_temp:] = temp_vdd[0:-temp_onset]
                            self.ESA_raw_data[channel_num][0:temp_onset] = temp_vdd[-temp_onset:]
                    else:
                        for channel_num in range(16):
                            # ESA通道使用奇数位置的Y轴偏移 (channel_num * 2 + 1)
                            self.ESA_raw_data[channel_num][ESA_pointer_temp:endpoint] = ESA_raw_data[channel_num] + (channel_num * 2 + 1) * self.separate_interval
                
                 # update raster data
                if(len(spike_raster_data_mode_1[0]) != 0):
                    endpoint = self.ring_spike_raster_pointer + len(spike_raster_data_mode_1[0])
                    if(endpoint > self.spike_raster_display_data_num ):
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
        

                """  mode 1  & 3"""
            elif(int(data[0][0]) == 1):
                """ spike raw data + raster data mode 1 """
                self.spike_raw_channel = data[0][1]
                spike_timestamp_mode_1 = np.array(data[1])
                spike_raw_data_mode_1 = np.array(data[2])
                spike_raster_data_mode_1 = np.array(data[4], dtype=np.float32)
                # curr timestamp
                self.spike_timestamp_note = spike_timestamp_mode_1[0]
                
                # maz interval between packets
                Interval_packets_max = 0
                if(self.current_sample_mode == 1):
                    Interval_packets_max = self.mSerial.Spike_max_interval
                elif(self.current_sample_mode == 3):
                    Interval_packets_max = self.mSerial.mode3_raw_max_interval
    
                # statitic dropped packets
                temp_loss = np.diff(spike_timestamp_mode_1) 
                temp_loss = temp_loss[(temp_loss > Interval_packets_max) | (temp_loss <= 0)]
                loss_packets_value = len(temp_loss // (Interval_packets_max - 1))
                # if(loss_packets_value > 0):
                #     print("raw data moide3:", Interval_packets_max, temp_loss[temp_loss > 0])
                self.spikemisspackets_mode_1 +=  loss_packets_value
                self.spikeaccumulpackets_mode_1 += len(spike_timestamp_mode_1)
                # 每save file一次就重新统计丢失的包的数量
                if(self.spikeaccumulpackets_mode_1 >= self.mSerial.file_size_mode1 * 10):
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
                # 如果开启滤波，更新滤波缓冲
                if self.spike_filter_enabled:
                    self._apply_spike_filter_buffer()

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
            
                """  mode 2  """
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
                if(self.spike_mode2_accumulpackets >= self.mSerial.file_size_mode2 * 10):
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
                            temp_vdd = np.array(spikeraw_data[channel_num]) + channel_num * self.separate_interval_spike
                            self.spike_mode2_raw_data[channel_num][self.ring_spike_mode2_pointer:] = temp_vdd[0:-temp_onset]
                            self.spike_mode2_raw_data[channel_num][0:temp_onset] = temp_vdd[-temp_onset:]
                    self.ring_spike_mode2_pointer = temp_onset
                else:
                    for channel_num in range(16):
                        if(self.spike_mode2_curr_channel[channel_num] == max(self.spike_mode2_curr_channel)):
                            self.spike_mode2_raw_data[channel_num][self.ring_spike_mode2_pointer:endpoint] = np.array(spikeraw_data[channel_num]) + channel_num * self.separate_interval_spike
                    self.ring_spike_mode2_pointer = endpoint # update indicater
                pass


            """ sensing data 9 data """
            if(int(data[0][0]) != 2):
                sensors_data = np.array(data[3], dtype=np.float32)
                sensor_end_point = self.ring_LSR_pointer + len(sensors_data[0])

                self.RSOC = int(sensors_data[6][-1])
                self.Battery_STAT = int(sensors_data[7][-1])
                self.Battery_voltage = int(sensors_data[8][-1])
                if(sensor_end_point > self.LSR_display_data_num):
                    temp_onset = sensor_end_point - self.LSR_display_data_num
                    for i in range(6):
                        self.IMUdata[i][self.ring_LSR_pointer:] = sensors_data[i][0:-temp_onset]
                        self.IMUdata[i][0:temp_onset] = sensors_data[i][-temp_onset:]

                    self.RSOC_stat[0][self.ring_LSR_pointer:] = sensors_data[6][0:-temp_onset]
                    self.RSOC_stat[0][0:temp_onset] = sensors_data[6][-temp_onset:]

                    self.STAT_stat[0][self.ring_LSR_pointer:] = (sensors_data[7][0:-temp_onset])
                    self.STAT_stat[0][0:temp_onset] = sensors_data[7][-temp_onset:] 

                    self.Voltage_stat[0][self.ring_LSR_pointer:] = (sensors_data[8][0:-temp_onset])
                    self.Voltage_stat[0][0:temp_onset] = sensors_data[8][-temp_onset:] 
                    
                    self.ring_LSR_pointer = temp_onset
                else:
                    try:
                        for i in range(6):
                            self.IMUdata[i][self.ring_LSR_pointer:sensor_end_point] = sensors_data[i]
                        self.RSOC_stat[0][self.ring_LSR_pointer:sensor_end_point] = sensors_data[6]
                        self.STAT_stat[0][self.ring_LSR_pointer:sensor_end_point] = sensors_data[7]
                        self.Voltage_stat[0][self.ring_LSR_pointer:sensor_end_point] = sensors_data[8]
                    except:
                        print(sensors_data[i])
                    self.ring_LSR_pointer = sensor_end_point


    """callback function"""
    def set_connected_port(self, port):
        """Set connected serial port"""
        self.curr_active_ports = port
        self.statusBar().showMessage(f"Connected to {port}")
        try:
        # start read data from Serial
            self.mSerial = SerialPort(self.curr_active_ports,2000000)
            self.mSerial.port_open()
            self.mSerial.GUIUpdate.connect(self.update_plot_data)
            self.mSerial.EmptyGUIUpdate.connect(self.update_idle_status)
            self.mSerial.CameraGUIUpdate.connect(self.update_carmera_status)
            self.mSerial.start()
            # RF power control status update
            self.rf_power_status_update()
            # # HABITS command
            self.habits_tab.habits_panel.Neural_recorder_command.connect(self.HABITS_command_process)
        except:
            print(sys.exc_info())
            QMessageBox.warning(self, "Warning", "Some init failed, please check the connection")
            pass
    
    def update_carmera_status(self):
        # 如果摄像头处于记录状态就保存一次文文件
        if(self.toggle_recording_button.text() == "Stop recording"):
            self.toggle_recording()
        # 检查是否摄像头已经打开，否则打开摄像头
        if(self.toggle_camera_button.text() == "Open camera"):
            self.toggle_camera()
        # 检查是否存在一个saving flag 为 true
        if(self.mSerial.save_file_lfp_flag or self.mSerial.save_file_mode3_flag):
            # 开始记录video
            self.toggle_recording()

    def rf_power_on(self):
        """打开RF功率"""
        if not self.rf_connected:
            QMessageBox.warning(self, "Warning", "RF控制串口未连接，请先连接串口")
            return
        
        try:
            # 发送RF功率开启命令
            command = b'\x01\x05\x00\x00\xFF\x00\x8C\x3A'
            self.rf_serial_connection.write(command)
            self.rf_serial_connection.flush()
            
            # 读取响应
            response = self.rf_serial_connection.read(8)
            if len(response) == 8 and response == command:
                self.rf_power_status = 2  # 开启状态
                self.rf_power_status_update()
                print("RF功率已开启")
            else:
                print("RF功率开启失败")
                
        except Exception as e:
            print(f"RF功率控制错误: {str(e)}")
        
    def rf_power_off(self):
        """关闭RF功率"""
        if not self.rf_connected:
            QMessageBox.warning(self, "Warning", "RF控制串口未连接，请先连接串口")
            return
        
        try:
            # 发送RF功率关闭命令
            command = b'\x01\x05\x00\x00\x00\x00\xCD\xCA'
            self.rf_serial_connection.write(command)
            self.rf_serial_connection.flush()
            
            # 读取响应
            response = self.rf_serial_connection.read(8)
            if len(response) == 8 and response == command:
                self.rf_power_status = 1  # 关闭状态
                self.rf_power_status_update()
                print("RF功率已关闭")
            else:
                print("RF功率关闭失败")
                
        except Exception as e:
            print(f"RF功率控制错误: {str(e)}")

    def rf_power_status_update(self):
        """更新RF功率状态显示"""
        if hasattr(self, 'rf_power_status'):
            if self.rf_power_status == 2:  # 开启状态
                self.rf_power_on_button.setStyleSheet(f"background-color: #66BB6A;")
                self.rf_power_off_button.setStyleSheet(f"background-color: #ffffff;")
            elif self.rf_power_status == 1:  # 关闭状态
                self.rf_power_off_button.setStyleSheet(f"background-color: #FF5252;")
                self.rf_power_on_button.setStyleSheet(f"background-color: #ffffff;")

    def rf_power_control(self):
        """
        控制逻辑：判定时间 10分钟一次
        以电池电量为控制变量
        电池50% 以下，打开电源
        电池80% 以上， 关闭电源
        电池电量20% 以下， idle 模式
        """    
        # print("Current RSOC", self.RSOC)
        
        # 只有在RF串口连接时才进行自动控制
        if not self.rf_connected:
            return
            
        current_rf_status = getattr(self, 'rf_power_status', 1)  # 默认为关闭状态
        
        if(self.RSOC < 50 and current_rf_status == 1): # 电量低且RF关闭时，开启RF
            self.rf_power_on()
            if(self.RSOC < 20):
                self.sample_stop()
                self.RF_turnoff = True
        elif(self.RSOC > 80 and current_rf_status == 2): # 电量高且RF开启时，关闭RF
            self.rf_power_off()
        
        if(self.RF_turnoff and self.RSOC > 20):
            self.sample_start()
            self.RF_turnoff = False
        
        
       

    def update_idle_status(self, status):
        self.RSOC = status[0]
        self.Battery_STAT = status[1]
        self.Battery_voltage = status[2]
        self.update_battery_indicator(self.RSOC, self.Battery_STAT, self.Battery_voltage)
    
    def start_save_lfp(self):
        # 文件路径检查
        if not hasattr(self.lfp_tab, 'lfp_file_path_label') or self.lfp_tab.lfp_file_path_label.text() == "File path don't selected":
            QMessageBox.warning(self, "warning", "请先选择LFP保存路径！")
            return
        # 互斥：仅开启LFP保存
        self.mSerial.save_file_lfp_flag = True
        self.mSerial.save_file_mode1_flag = False
        self.mSerial.save_file_mode2_flag = False
        self.mSerial.save_file_mode3_flag = False
        # 路径设置
        self.mSerial.lfp_file_addr = self.lfp_tab.lfp_file_path_label.text()
        # 更新按钮状态
        self.lfp_tab.start_save_button.setEnabled(False)
        self.lfp_tab.stop_save_button.setEnabled(True)
        # 关闭其他面板的保存按钮状态
        self.spike1ch_tab.start_save_button.setEnabled(True)
        self.spike1ch_tab.stop_save_button.setEnabled(False)
        self.spike4ch_tab.start_save_button.setEnabled(True)
        self.spike4ch_tab.stop_save_button.setEnabled(False)
        self.lfp_tab.start_save_mode3_button.setEnabled(True)
        self.lfp_tab.stop_save_mode3_button.setEnabled(False)
        # 开始 video 记录
        self.update_carmera_status()

    def stop_save_lfp(self):
        self.mSerial.save_file_lfp_flag = False
        # self.mSerial.lfp_file_addr = ""
        # 更新按钮状态
        self.lfp_tab.start_save_button.setEnabled(True)
        self.lfp_tab.stop_save_button.setEnabled(False)

    def start_save_mode1(self):
        # 文件路径检查
        if not hasattr(self.spike1ch_tab, 'mode1_file_path_label') or self.spike1ch_tab.mode1_file_path_label.text() == "File path don't selected":
            QMessageBox.warning(self, "warning", "请先选择Mode1保存路径！")
            return
        # 互斥：仅开启Mode1保存
        self.mSerial.save_file_lfp_flag = False
        self.mSerial.save_file_mode1_flag = True
        self.mSerial.save_file_mode2_flag = False
        self.mSerial.save_file_mode3_flag = False
        # 路径设置
        self.mSerial.mode1_file_addr = self.spike1ch_tab.mode1_file_path_label.text()
        # 更新按钮状态
        self.spike1ch_tab.start_save_button.setEnabled(False)
        self.spike1ch_tab.stop_save_button.setEnabled(True)
        self.lfp_tab.start_save_button.setEnabled(True)
        self.lfp_tab.stop_save_button.setEnabled(False)
        self.lfp_tab.start_save_mode3_button.setEnabled(True)
        self.lfp_tab.stop_save_mode3_button.setEnabled(False)
        self.spike4ch_tab.start_save_button.setEnabled(True)
        self.spike4ch_tab.stop_save_button.setEnabled(False)

    def stop_save_mode1(self):
        self.mSerial.save_file_mode1_flag = False
        # 更新按钮状态
        self.spike1ch_tab.start_save_button.setEnabled(True)
        self.spike1ch_tab.stop_save_button.setEnabled(False)

    
    def start_save_mode2(self):
        # 文件路径检查
        if not hasattr(self.spike4ch_tab, 'file_path_label') or self.spike4ch_tab.file_path_label.text() == "file path don't selected":
            QMessageBox.warning(self, "warning", "请先选择Mode2保存路径！")
            return
        # 互斥：仅开启Mode2保存
        self.mSerial.save_file_lfp_flag = False
        self.mSerial.save_file_mode1_flag = False
        self.mSerial.save_file_mode2_flag = True
        self.mSerial.save_file_mode3_flag = False
        # 路径设置
        self.mSerial.mode2_file_addr = self.spike4ch_tab.file_path_label.text()
        # 更新按钮状态
        self.spike4ch_tab.start_save_button.setEnabled(False)
        self.spike4ch_tab.stop_save_button.setEnabled(True)
        self.lfp_tab.start_save_button.setEnabled(True)
        self.lfp_tab.stop_save_button.setEnabled(False)
        self.lfp_tab.start_save_mode3_button.setEnabled(True)
        self.lfp_tab.stop_save_mode3_button.setEnabled(False)
        self.spike1ch_tab.start_save_button.setEnabled(True)
        self.spike1ch_tab.stop_save_button.setEnabled(False)

    def stop_save_mode2(self):
        self.mSerial.save_file_mode2_flag = False
        self.mSerial.mode2_file_addr = ""
        # 更新按钮状态
        self.spike4ch_tab.start_save_button.setEnabled(True)
        self.spike4ch_tab.stop_save_button.setEnabled(False)

    def start_save_mode3(self):
        # 文件路径检查
        if not hasattr(self.lfp_tab, 'mode3_file_path_label') or self.lfp_tab.mode3_file_path_label.text() == "File path don't selected":
            QMessageBox.warning(self, "warning", "请先选择Mode3保存路径！")
            return
        # 互斥：仅开启Mode3保存
        self.mSerial.save_file_lfp_flag = False
        self.mSerial.save_file_mode1_flag = False
        self.mSerial.save_file_mode2_flag = False
        self.mSerial.save_file_mode3_flag = True
        # 路径设置
        self.mSerial.mode3_file_addr = self.lfp_tab.mode3_file_path_label.text()
        # 更新按钮状态
        self.lfp_tab.start_save_mode3_button.setEnabled(False)
        self.lfp_tab.stop_save_mode3_button.setEnabled(True)
        self.lfp_tab.start_save_button.setEnabled(True)
        self.lfp_tab.stop_save_button.setEnabled(False)
        self.spike4ch_tab.start_save_button.setEnabled(True)
        self.spike4ch_tab.stop_save_button.setEnabled(False)
        self.spike1ch_tab.start_save_button.setEnabled(True)
        self.spike1ch_tab.stop_save_button.setEnabled(False)

         # 开始 video 记录
        self.update_carmera_status()

    def stop_save_mode3(self):
        self.mSerial.save_file_mode3_flag = False
        # 更新按钮状态
        self.lfp_tab.start_save_mode3_button.setEnabled(True)
        self.lfp_tab.stop_save_mode3_button.setEnabled(False)

    def sample_start(self):
        self.mSerial.flush()
        for i in range(1):    
            self.open_command = [0x01 ,0x00] 
            self.mSerial.send_data(self.open_command)
            time.sleep(0.1)

    def sample_stop(self):
        self.close_command = [0x02 ,0x00] # invalid sample mode
        self.mSerial.send_data(self.close_command)

    def sample_mode_switch(self, mode=None): # 切换选项卡的时候就会触发 模式的改变
        if(mode == None):
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
    
    def IMU_mode_setting(self):
        self.IMU_command = [0x03, 0x00 ,  0x00 ,0x00] 
        # battery_mode
        self.IMU_command[-2] = int(hex(self.battery_status_combo.currentIndex() + 1) ,16)
        print(self.IMU_command)
        self.err = self.mSerial.send_data(self.IMU_command)

    def HABITS_command_process(self, command):
        # 根据模式来开启和关闭当前trialblock的数据保存
        if(int(command) == 1): # trial block end 
            # mode3 file saved
            self.mSerial.save_file_mode3_flag = False
            if hasattr(self.lfp_tab, 'mode3_file_path_label'):
                self.mSerial.mode3_file_addr = self.lfp_tab.mode3_file_path_label.text()
            self.sample_mode_switch(int(command) - 1)  # 2 -> mode3; 1-> mode0
            self.mSerial.save_file_lfp_flag = True
        elif(int(command) == 4): # trial block onset -> file saving
            # 保存 lfp 数据
            self.mSerial.save_file_lfp_flag = False
            # mode3 file save begin
            self.sample_mode_switch(int(command) - 1)  # 2 -> mode3; 1-> mode0
            self.mSerial.save_file_mode3_flag = True
            if hasattr(self.lfp_tab, 'mode3_file_path_label'):
                self.mSerial.mode3_file_addr = self.lfp_tab.mode3_file_path_label.text()

        pass
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


    

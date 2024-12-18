import re
import sys
import time

import PyQt6
from PyQt6 import QtWidgets
from PyQt6.QtCore import pyqtSignal

import pyqtgraph as pg

import QtESBV3.Channel_UI as Channel_UI
import QtESBV3.Filter_UI as Filter_UI

import numpy as np
from scipy import signal, fft


class FilterWin(QtWidgets.QWidget, Filter_UI.Ui_Form):
    confirm_sig = pyqtSignal(str)

    def __init__(self):
        super(FilterWin, self).__init__()
        self.setupUi(self)

        self.btn_init()
        self.sig_init()

        self.filter_class = ""
        self.filter_order = 0
        self.filter_up_freq = 0
        self.filter_down_freq = 0

        self.DownFilter_LE.setEnabled(False)

    def btn_init(self):
        self.Confirm_Btn.clicked.connect(self.confirm_I)

    def sig_init(self):
        self.Filter_CB.currentIndexChanged.connect(self.filter_changed)

    def filter_changed(self):
        if self.Filter_CB.currentText() == "低通滤波器" or \
                self.Filter_CB.currentText() == "高通滤波器":
            self.DownFilter_LE.setEnabled(False)
        elif self.Filter_CB.currentText() == "带通滤波器" or \
                self.Filter_CB.currentText() == "带阻滤波器":
            self.DownFilter_LE.setEnabled(True)

    def set_data(self):
        self.filter_class = self.Filter_CB.currentText()
        self.filter_order = self.FilterOrder_LE.text()
        self.filter_up_freq = self.UpFilter_LE.text()
        self.filter_down_freq = self.DownFilter_LE.text()

    def get_data(self):
        return self.filter_class, self.filter_order, self.filter_up_freq, self.filter_down_freq

    def confirm_I(self):
        self.confirm_sig.emit('confirm')
        self.set_data()
        self.close()


class ChannelWin(QtWidgets.QWidget, Channel_UI.Ui_Form):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.filter_win = FilterWin()

        self.is_data_in_time = True
        self.channel = None
        self.channel_data = None

        self.spike_data = None
        self.raw_timestamp = None
        self.spike_timestamp = None

        self.data_pg = None
        self.data_pg2 = None
        self.data_curve = None
        self.data_curve2 =None

        self.sample_rate = 0

        self.filter_class = ""
        self.filter_order = 0
        self.filter_up_freq = 0
        self.filter_down_freq = 0

        self.ESB_Channel = False

        self.btn_init()
        self.sig_init()
        self.pg_init()

    def handle_click(self):
        self.ESB_Channel = True
        self.show()

    def closeEvent(self, event):
        self.data_pg.clearPlots()
        self.data_pg2.clearPlots()
        self.ESB_Channel = False
        event.accept()

    def btn_init(self):
        self.SetTimeFreq_Btn.clicked.connect(self.time_freq_change_I)
        self.SetFilter_Btn.clicked.connect(self.set_filter_I)

    def sig_init(self):
        self.filter_win.confirm_sig.connect(self.set_filter_para)

    def pg_init(self):
        self.DataGraph_1.setBackground("black")
        self.data_pg = self.DataGraph_1.addPlot(title="")
        self.data_curve = self.data_pg.plot(pen='w')

        self.DataGraph_2.setBackground("black")
        self.data_pg2 = self.DataGraph_2.addPlot(title="")
        self.data_curve2 = self.data_pg2.plot(pen='w')
    def plot_init(self):
        self.data_curve = self.data_pg.plot(pen='w')
        self.data_curve2 = self.data_pg2.plot(pen='w')
    def set_data(self, channel, raw_timestamp ,raw_data ,spike_timestamp ,spike_data, sample_rate=1000):
        self.channel = channel
        self.channel_data = raw_data
        self.spike_data = spike_data
        self.sample_rate = sample_rate
        self.raw_timestamp = raw_timestamp
        self.spike_timestamp = spike_timestamp
        # 其中spike 的输入为一个 16 * n shape;
        for i in range(16):
            self.spike_data[i][self.spike_data[i] == 1] = self.spike_data[i][self.spike_data[i] == 1] + i

        self.Channel_Label.setText('通道: ' + str(self.channel))
        try:
            # raw data
            self.data_curve.setData(self.raw_timestamp, np.array(self.channel_data))
            #TODO spike raster data 怎么去绘制多条图层
            # self.data_curve2.setData(self.spike_timestamp ,np.array(self.spike_data))
        except Exception as ex:
            print("绘图错误" + str(ex))


    def time_freq_change_I(self):
        if not self.channel_data:
            return

        if self.is_data_in_time:
            # TODO: 加入频域设置
            fft_data = fft.fft(self.channel_data)

            _list = np.array(range(0, int(len(self.channel_data) / 2)))
            xf = self.sample_rate * _list / len(self.channel_data)
            amp = np.array(np.abs(fft_data) / len(self.channel_data) * 2)
            amp = amp[0: int(len(self.channel_data) / 2)]

            try:
                self.data_pg.clearPlots()
                self.data_pg.plot(x=xf, y=amp, pen=pg.mkPen(color=(255, 0, 0), width=2))
            except Exception as ex:
                print("绘图错误" + str(ex))

            self.is_data_in_time = False
            self.SetTimeFreq_Btn.setText("转换时域")
        else:
            try:
                self.data_pg.clearPlots()
                self.data_curve = self.data_pg.plot(pen='w')
                print(len(self.channel_data))
                self.data_curve.setData(np.array(self.channel_data))
            except Exception as ex:
                print("绘图错误" + str(ex))

            self.is_data_in_time = True
            self.SetTimeFreq_Btn.setText("转换频域")

    def set_filter_I(self):
        self.filter_win.show()

    def set_filter_para(self):
        if not self.is_data_in_time:
            sos, filtered_data = None, None

            try:
                self.filter_class, self.filter_order, self.filter_up_freq, self.filter_down_freq = self.filter_win.get_data()
                if self.filter_class == "低通滤波器":
                    sos = signal.butter(int(self.filter_order), int(self.filter_up_freq), 'lowpass', fs=self.sample_rate, output='sos')
                elif self.filter_class == "高通滤波器":
                    sos = signal.butter(int(self.filter_order), int(self.filter_up_freq), 'highpass', fs=self.sample_rate, output='sos')
                elif self.filter_class == "带通滤波器":
                    sos = signal.butter(int(self.filter_order), [int(self.filter_up_freq), int(self.filter_down_freq)], 'bandpass', fs=self.sample_rate, output='sos')
                elif self.filter_class == "带阻滤波器":
                    sos = signal.butter(int(self.filter_order), [int(self.filter_up_freq), int(self.filter_down_freq)], 'bandstop', fs=self.sample_rate, output='sos')

                filtered_data = signal.sosfilt(sos, self.channel_data)
            except Exception as ex:
                print("滤波出错" + str(ex))

            if not filtered_data:
                fft_data = fft.fft(filtered_data)

                _list = np.array(range(0, int(len(filtered_data) / 2)))
                xf = self.sample_rate * _list / len(filtered_data)
                amp = np.array(np.abs(fft_data) / len(filtered_data) * 2)
                amp = amp[0: int(len(filtered_data) * 2)]

                try:
                    self.data_pg.clearPlots()
                    self.data_pg.plot(x=xf, y=amp, pen=pg.mkPen(color=(255, 255, 0), width=2))
                except Exception as ex:
                    print("绘图错误" + str(ex))

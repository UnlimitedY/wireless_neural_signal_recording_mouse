import re
import sys
import time

import PyQt5
from PyQt5 import QtWidgets
import PyQt5.QtBluetooth as QtBt

import QtESBV3.BLE_UI as BLE_UI
import QtESBV3.BLE_Channel as BLE_Channel

import numpy as np


class BLEState:
    def __init__(self):
        self.is_connect = False
        self.data_notify = False
        
        self.write_uuid = None
        self.read_uuid = None
        

class ctrlWindow(QtWidgets.QMainWindow, BLE_UI.Ui_MainWindow):
    def __init__(self):
        super(ctrlWindow, self).__init__()
        self.setupUi(self)

        self.btn_init()
        self.sig_init()

        self.controls_init()

        # var
        self.channel_win = BLE_Channel.ChannelWin()
        
        self.agent = QtBt.QBluetoothDeviceDiscoveryAgent()
        self.scan_timer = PyQt5.QtCore.QTimer(self.agent)

        self.serviceUUID = list()
        
        self.is_connected = False
        self.data_notify = False
        self.is_data_transfer = False
        
        self.write_uuid = None
        self.read_uuid = None
        self.notify_uuid = None
        
        self.ble_controller = None
        self.ServiceObject = None
        
        self.max_show_len = 10000
        self.sample_rate = 0
        self.signal_win_len = 0
        
        self.data_values = [[] for j in range(16)]
        self.DataGraphs = [self.DataGraph_1, self.DataGraph_2, self.DataGraph_3, self.DataGraph_4,
                           self.DataGraph_5, self.DataGraph_6, self.DataGraph_7, self.DataGraph_8,
                           self.DataGraph_9, self.DataGraph_10, self.DataGraph_11, self.DataGraph_12,
                           self.DataGraph_13, self.DataGraph_14, self.DataGraph_15, self.DataGraph_16]
        self.data_pgs = list()
        self.data_curves = list()

        self.pg_init()

        # self.ble_thread = BLEModule.BLEControl()
        # self.ble_thread.start()
        # self.ble_thread.state_sig.connect(self.status_changed)
        # self.ble_thread.msg_sig.connect(self.ble_thread_I)
        # self.ble_thread.server_msg.connect(self.add_server)

    def btn_init(self):
        self.Scan_Btn.clicked.connect(self.scan_btn_I)
        self.Connect_Btn.clicked.connect(self.connect_btn_I)
        self.ClearData_Btn.clicked.connect(self.clear_data_I)

        self.DataSend_Btn.clicked.connect(self.send_data_win_I)
        self.DataRead_Btn.clicked.connect(self.data_read_I)
        self.DataReadCont_Btn.clicked.connect(self.data_read_continues_I)
        self.DataNotify_Btn.clicked.connect(self.data_notify_I)
        
        self.DataRecStop_Btn.clicked.connect(self.order_send_I)
        self.ClearPG_Btn.clicked.connect(self.clear_pg_I)
        self.DataCheck_Btn.clicked.connect(self.data_check_I)

    def sig_init(self):
        self.SampleRate_LE.textChanged.connect(self.sample_rate_change_I)
        self.SignalLen_LE.textChanged.connect(self.signal_len_change_I)

    def controls_init(self):
        self.Scan_CB.setEnabled(False)
        self.Server_CB.setEnabled(False)
        self.Character_CB.setEnabled(False)

    def pg_init(self):
        labels = {'left': 'value', 'bottom': 'time/ms'}
        # self.DataGraph_1.setBackground(None)
        # self.data_pg = self.DataGraph_1.addPlot(title="")
        # self.data_curve = self.data_pg.plot(pen='b', name='data')
        for i in range(16):
            self.DataGraphs[i].setBackground("black")
            data_pg = self.DataGraphs[i].addPlot(title="")
            data_curve = data_pg.plot(pen='w')
            self.data_pgs.append(data_pg)
            self.data_curves.append(data_curve)

    def scan_btn_I(self):
        print('ble scan')
        self.agent.setLowEnergyDiscoveryTimeout(5000)
        self.agent.deviceDiscovered.connect(self.device_discovered)
        self.agent.error.connect(self.agent_error)
        self.agent.finished.connect(self.agent_finished)

        self.scan_timer.start(5)
        self.scan_timer.timeout.connect(self.display_status)
        self.agent.start()
        
        self.Scan_CB.setEnabled(False)
        self.status_changed("green", "正在搜索蓝牙设备")

    def device_discovered(self, info: QtBt.QBluetoothDeviceInfo):
        if int(info.coreConfigurations()) == 1:
            print(f'Name: {info.name()}, Address: {info.address().toString()}, server UUID: {info.serviceUuids()}')

    def agent_error(self, e):
        error = ["NoError", "InputOutputError", "PoweredOffError", "InvalidBluetoothAdapterError", "UnknownError"]
        if e < 4:
            print(error[e])
        else:
            print(error[4])

    def agent_finished(self):
        for dev in self.agent.discoveredDevices():
            if dev.coreConfigurations() and QtBt.QBluetoothDeviceInfo.LowEnergyCoreConfiguration:
                print(f'设备名称: {dev.name()} 设备地址: {dev.address()}')
                if not dev.name().startswith("Bluetooth"):
                    self.Scan_CB.addItem(dev.name())
        self.Scan_CB.setEnabled(True)

        self.status_changed("green", "搜索完成")

    def display_status(self):
        print(self.agent.isActive(), self.agent.discoveredDevices())
        self.scan_timer.stop()

    def connect_btn_I(self):
        if not self.is_connected:
            for dev in self.agent.discoveredDevices():
                if dev.name() == self.Scan_CB.currentText():
                    self.status_changed("green", f"正在连接{dev.name()}")

                    self.ble_controller = QtBt.QLowEnergyController.createCentral(dev, self)
                    self.ble_controller.connected.connect(self.ble_connect_finished)
                    self.ble_controller.error.connect(self.ble_controller_error)
                    self.ble_controller.disconnected.connect(self.ble_disconnect_finished)
                    self.ble_controller.serviceDiscovered.connect(self.add_service)
                    self.ble_controller.discoveryFinished.connect(self.service_discover_finished)
                    self.ble_controller.connectToDevice()
                    break
        elif self.is_connected:
            self.ble_controller.disconnectFromDevice()

    def ble_connect_finished(self, *args, **kwargs):
        self.serviceUUID = list()
        self.ble_controller.discoverServices()

        self.is_connected = True
        self.Server_CB.setEnabled(False)
        self.status_changed("green", "连接成功")
        self.Connect_Btn.setText("断开连接")

    def ble_controller_error(self):
        pass

    def ble_disconnect_finished(self, *args, **kwargs):
        self.ble_controller.connected.disconnect(self.ble_connect_finished)
        self.ble_controller.error.disconnect(self.ble_controller_error)
        self.ble_controller.disconnected.disconnect(self.ble_disconnect_finished)
        self.ble_controller.serviceDiscovered.disconnect(self.add_service)
        self.ble_controller.discoveryFinished.disconnect(self.service_discover_finished)

        self.Connect_Btn.setText("连接")
        # 断开 Scan_CB Server_CB Character_CB 的连接
        self.Server_CB.currentTextChanged.disconnect(self.server_changed)
        self.Server_CB.setEnabled(True)
        self.Server_CB.clear()
        self.Server_CB.setEnabled(False)
        self.Character_CB.clear()
        self.Character_CB.setEnabled(False)
        # 删除所有对象
        self.ServiceObject = None
        self.ble_controller = None
        # 变量
        self.is_connected = False
        self.ble_controller = None
        self.status_changed("green", "断开连接成功")

    def add_service(self, uuid: QtBt.QBluetoothUuid):
        self.status_changed("green", f"发现服务 Service discovered {uuid.toString()}")
        print(f'发现服务 Service discovered  uuid: {uuid.toString()}')
        self.serviceUUID.append(uuid)
        self.Server_CB.addItem(uuid.toString())

    def service_discover_finished(self):
        self.Server_CB.currentTextChanged.connect(self.server_changed)
        self.Server_CB.setEnabled(True)
        self.status_changed("green", "服务搜索完成")
        print(f'服务搜索完成')

    def server_changed(self):
        for uuid in self.serviceUUID:
            if uuid.toString() == self.Server_CB.currentText():
                self.ServiceObject = self.ble_controller.createServiceObject(uuid)
                break
        if self.ServiceObject is None:
            print(f'服务连接失败')

            self.status_changed("red", "服务连接失败")
        else:
            print(f'服务连接成功')
            self.status_changed("green", "服务连接成功")

            self.ServiceObject.stateChanged.connect(self.server_state_changed)
            self.ServiceObject.characteristicWritten.connect(self.characteristic_written)
            self.ServiceObject.error.connect(self.service_error)
            time.sleep(1)
            self.ServiceObject.discoverDetails()

    def server_state_changed(self, s):
        print(f'服务状态变化通知:{s} state:{self.ServiceObject.state()}')

        try:
            if s == QtBt.QLowEnergyService.DiscoveringServices:
                print(f"正在搜索服务特征... Discovering services...")
                self.status_changed("green", "正在搜索服务特征...")
            elif s == QtBt.QLowEnergyService.ServiceDiscovered:
                print(f"搜索服务特征完成. Service discovered.")

                self.status_changed("green", "搜索服务特征完成")

                self.Character_CB.clear()
                for ch in self.ServiceObject.characteristics():
                    self.Character_CB.addItem(ch.uuid().toString())
                    if "8653000b" in ch.uuid().toString():
                        self.read_uuid = ch.uuid()
                        self.notify_uuid = ch.uuid()
                    elif "8653000c" in ch.uuid().toString():
                        self.write_uuid = ch.uuid()
                    # if "fff1" in ch.uuid().toString():
                    #     self.read_uuid = ch.uuid()
                    #     self.notify_uuid = ch.uuid()
                    # elif "fff2" in ch.uuid().toString():
                    #     self.write_uuid = ch.uuid()
                self.Character_CB.setEnabled(True)
        except Exception as ex:
            print(ex)

    def characteristic_written(self):
        pass

    def service_error(self):
        pass

    def send_data_win_I(self):
        _data = self.DataSend_Line.text()
        print(_data)
        if self.Hex_Cb.isChecked():
            _data = re.findall(r'[0-9a-fA-F]{2}', _data)
            _send = bytes([(int(d, 16)) for d in _data])
        else:
            _send = bytes([d for d in bytearray(_data, "utf-8")])
        self.data_send_I(_send)
            
    def data_send_I(self, data):
        print(data)
        try:
            write_character = self.ServiceObject.characteristic(self.write_uuid)
            if write_character.isValid():
                self.ServiceObject.writeCharacteristic(write_character, data, QtBt.QLowEnergyService.WriteWithoutResponse)
        except AttributeError as ex:
            print(ex)


    def data_read_I(self):
        pass

    def data_read_continues_I(self):
        pass

    def data_notify_I(self):
        if self.is_connected and not self.data_notify:
            self.data_notify = True

            if self.ServiceObject:
                # for ch in self.ServiceObject.characteristics():
                #     if ch.uuid().toString() == self.Character_CB.currentText():
                #         self.characteristicRead_ = self.ServiceObject.characteristic(ch.uuid())
                #         break
                
                self.characteristicRead_ = self.ServiceObject.characteristic(self.notify_uuid)

                try:
                    if not self.characteristicRead_.isValid():
                        self.status_changed("red", "创建监听特征失败，读特征不可用.")
                        return
                except Exception as ex:
                    print(ex)

                self.status_changed("green", "创建监听特征成功，正在设置监听...")

                try:
                    self.notification = self.characteristicRead_.descriptors()[0]
                    print(f'self.notification is {self.notification}')
                    # 判断读特征描述符是否可用
                    print(f'read_notify.isValid:{self.notification.isValid()}')
                    if not self.notification.isValid():
                        self.status_changed("red", "监听特征描述符不可用，监听失败.")
                        return
                except Exception as ex:
                    print(ex)

                try:
                    # 绑定监听函数
                    self.ServiceObject.characteristicChanged.connect(self.characteristic_Changed)
                    # 写0x01,0x00启用监听服务
                    self.ServiceObject.writeDescriptor(self.notification, bytes.fromhex('0100'))

                    self.status_changed("green", "设置监听服务成功，正在监听数据...")
                    
                    self.DataNotify_Btn.setText("取消订阅")
                except Exception as ex:
                    print(ex)
                    
        elif self.data_notify == True:
            try:
                self.DataNotify_Btn.setText("订阅")
            except Exception as ex:
                print(ex)

    def characteristic_Changed(self, info, value):
        # print(f'特征读取变化通知')
        # 显示
        # if self.Hex_Cb.isChecked():
        #     self.DataRead_Text.setText(str(value.data()))
        # else:
        #     self.DataRead_Text.setText(str(value.data().decode("utf-8", "ignore")))
        
        # ch = info.uuid().toString() + "...."
        
        # 数据分16个通道显示
        
        dt = np.dtype(np.int16)
        dt = dt.newbyteorder('>')
        value_int16 = np.frombuffer(value, dtype=dt).tolist()

        index = value_int16[3]
        data = [value_int16[i] * 0.195 for i in range(len(value_int16)) if i >= 4]

        self.data_values[index].extend(data)
        try:
            if len(self.data_values[index]) < self.max_show_len:
                self.data_curves[index].setData(np.array(self.data_values[index]))
            else:
                self.data_curves[index].setData(np.array(self.data_values[index][-self.max_show_len:]))
        except Exception as ex:
            print("绘图错误" + str(ex))
        # self.data_value = np.append(self.data_value, num_value)
        # try:
        #     if len(self.data_value) < 100000:
        #         self.data_curve.setData(self.data_value)
        #     else:
        #         self.data_curve.setData(self.data_value[-100000:])
        # except Exception as ex:
        #     print(ex)

    def clear_data_I(self):
        self.DataRead_Text.setText('')

    def clear_pg_I(self):
        for i in range(16):
            self.data_curves[i].setData(np.empty(0))

    def status_changed(self, color, msg):
        self.BLEState_Label.setStyleSheet(f"background-color:{color}")
        self.BLEState_Label.setText(f"状态：{msg}")
        
    def order_send_I(self):
        start_transfer_order = [0x12, 0x13]
        stop_transfer_order = [0x12, 0x14]
        
        if not self.is_data_transfer:
            self.data_send_I(bytes(start_transfer_order))
            self.DataRecStop_Btn.setText("停止发送")
        else:
            self.data_send_I(bytes(stop_transfer_order))
            self.DataRecStop_Btn.setText("开始发送")
            
    def data_check_I(self):
        # if self.is_data_transfer and self.Channel_CB.currentText != "None channel":
        #     pass
        if self.Channel_CB.currentText != "None channel":
            channel = int(re.findall(r'[0-9]+', self.Channel_CB.currentText())[0])
            
            if self.sample_rate == 0:
                self.channel_win.set_data(channel, self.data_values[channel-1][-self.signal_win_len:])
            else:
                self.channel_win.set_data(channel, self.data_values[channel-1][-self.signal_win_len:], self.sample_rate)
            self.channel_win.handle_click()
            
    def sample_rate_change_I(self):
        self.sample_rate = int(self.SampleRate_LE.text())

    def signal_len_change_I(self):
        self.signal_win_len = int(self.SignalLen_LE.text())


if __name__ == '__main__':
    app = PyQt5.QtWidgets.QApplication(sys.argv)
    main_win = ctrlWindow()
    main_win.show()

    sys.exit(app.exec_())

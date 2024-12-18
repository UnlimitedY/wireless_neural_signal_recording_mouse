import numpy as np
import serial
from aioserial import AioSerial
import asyncio
import time
from multiprocessing import Process


from PyQt6.QtCore import QObject, pyqtSignal
from multiprocessing import Process, Queue

# 定义一个独立进程
class Worker(QObject):
    finished = pyqtSignal()  # 自定义信号，用于通知任务完成
    result = pyqtSignal(list)  # 自定义信号，用于传递结果
 
    def __init__(self):
        super().__init__()
        self.lise = []
        self.counter = 0
    def do_work(self):
        self.read_serial()

        # 发送结果信号
        
 
        # 发送完成信号


    def read_serial(self):
        serial2 = serial.Serial('COM11', 9600)
        while True:
            self.counter += 1
            a = time.time()
            line = serial2.read_all()
            if(len(line) != 0):
                print("giguigiu", len(line))
                print(line[-10:])
                print("reader" ,time.time() - a)
            if not line:
                continue
            self.lise.append(len(line))
            if(self.counter > 10):
                self.counter = 0
                self.finished.emit()
                self.result.emit(self.lise)

def worker_process():
    # 创建Worker对象
    worker = Worker()
    # 连接信号与槽
    worker.result.connect(print)
    worker.finished.connect(lambda: print("Worker finished"))
    # 执行任务
    worker.do_work()


def main():

    process = Process(target=worker_process)
    process.start()
    # process.join()

if __name__ == '__main__':
    # 启动独立进程
    ede = 0
    main()


    while(True):
        b = time.time()
        for i in range(1000000):
            ede += 1
        # time.sleep(1)
        # print("main" ,time.time() - b)
    

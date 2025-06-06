import cv2
import time
import os
import datetime
import threading
import numpy as np

class CameraModule:
    def __init__(self):
        self.camera = None
        self.is_camera_open = False
        self.is_recording = False
        self.recording_thread = None
        self.video_writer = None
        self.frame = None
        self.frame_processed = False  # 添加帧处理标记
        self.lock = threading.Lock()
        
    def open_camera(self, camera_id=0):
        """打开摄像头"""
        if not self.is_camera_open:
            try:
                # 尝试不同的后端
                backends = [cv2.CAP_ANY, cv2.CAP_DSHOW]
                
                for backend in backends:
                    print(f"尝试使用后端 {backend} 打开摄像头...")
                    self.camera = cv2.VideoCapture(camera_id, backend)
                    
                    # 检查摄像头是否成功打开
                    if self.camera.isOpened():
                        # 尝试读取一帧，确认摄像头工作正常
                        ret, test_frame = self.camera.read()
                        if ret:
                            print(f"成功使用后端 {backend} 打开摄像头")
                            
                            # 设置分辨率为480p (640x480)
                            print("(width, height)" ,self.camera.get(cv2.CAP_PROP_FRAME_WIDTH), self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            # self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                            # self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                            
                            # 设置缓冲区大小为1，减少延迟
                            self.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                            
                            self.is_camera_open = True
                            return True
                        else:
                            print(f"使用后端 {backend} 打开摄像头成功，但无法读取帧")
                            self.camera.release()
                    else:
                        print(f"使用后端 {backend} 无法打开摄像头")
                
                # 如果所有后端都失败，尝试降低分辨率
                print("尝试使用较低分辨率打开摄像头...")
                self.camera = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
                if self.camera.isOpened():
                    # 设置较低的分辨率
                    self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                    self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                    
                    # 测试是否可以读取帧
                    ret, test_frame = self.camera.read()
                    if ret:
                        print("成功使用较低分辨率打开摄像头")
                        self.is_camera_open = True
                        return True
                
                print("无法打开摄像头，请检查摄像头连接或驱动程序")
                return False
                
            except Exception as e:
                print(f"打开摄像头时出错: {e}")
                return False
        return True
        
    def close_camera(self):
        """关闭摄像头"""
        if self.is_camera_open:
            if self.is_recording:
                self.stop_recording()
                
            if self.camera:
                self.camera.release()
                
            self.is_camera_open = False
            self.frame = None
    
    def get_frame(self):
        """获取当前帧并添加时间戳"""
        if not self.is_camera_open:
            return None
        
        # 尝试多次读取帧，以应对偶尔的读取失败
        max_attempts = 3
        for attempt in range(max_attempts):
            ret, frame = self.camera.read()
            if ret:
                break
            print(f"读取帧失败，尝试 {attempt+1}/{max_attempts}")
            time.sleep(0.01)  # 减少等待时间，提高响应速度
        
        if not ret:
            print("多次尝试读取帧均失败，请检查摄像头连接")
            return None
            
        # 添加时间戳 - 确保每次都获取最新时间
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # 增加毫秒显示
        cv2.putText(
            frame, 
            current_time, 
            (10, 30), 
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.8, 
            (255, 255, 255), 
            2, 
            cv2.LINE_AA
        )
        
        with self.lock:
            self.frame = frame.copy()
            self.frame_processed = False  # 新帧未处理
            
        return frame
    
    def start_recording(self, save_path=None):
        """开始录制视频"""
        if not self.is_camera_open or self.is_recording:
            return False
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if save_path is None:
            # 创建保存目录
            save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
            os.makedirs(save_dir, exist_ok=True)
            
            # 生成文件名
            save_path = os.path.join(save_dir, f"video_{timestamp}.avi")
        else:
            save_path =  f"{save_path[0:-4]}_{timestamp}.avi"
        
        # 获取摄像头帧率
        fps = self.camera.get(cv2.CAP_PROP_FPS)
        print("fps:", fps)
        if fps <= 0 or fps > 100:
            fps = 30.0  # 默认帧率，确保合理值
            
        # 创建视频写入器
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        self.video_writer = cv2.VideoWriter(
            save_path, 
            fourcc, 
            fps, 
            (int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)), 
             int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        )
        
        self.is_recording = True
        
        # 启动录制线程
        self.recording_thread = threading.Thread(target=self._record_video)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
        return True
    
    def _record_video(self):
        """录制视频的线程函数"""
        # 计算基于摄像头帧率的休眠时间
        fps = self.camera.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or fps > 100:
            fps = 30.0
        
        sleep_time = 0.01  # 根据帧率调整休眠时间;设置为2倍的刷新率来减少丢帧的风险
         
        while self.is_recording and self.is_camera_open:
            with self.lock:
                if self.frame is not None and not self.frame_processed:
                    self.video_writer.write(self.frame)
                    self.frame_processed = True  # 标记为已处理
            
            # 根据摄像头帧率休眠，避免过度循环
            time.sleep(sleep_time)
    
    def stop_recording(self):
        """停止录制视频"""
        if self.is_recording:
            self.is_recording = False
            
            # 等待录制线程结束
            if self.recording_thread:
                self.recording_thread.join(timeout=1.0)
                self.recording_thread = None
            
            # 释放视频写入器
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
                
            return True
        return False
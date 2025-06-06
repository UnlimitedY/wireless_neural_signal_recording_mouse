import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
from scipy.signal import savgol_filter

# 设置 matplotlib 样式
plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
plt.rcParams['font.size'] = 12  # 设置所有字体大小

# 文件路径
file_path = r"E:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV3\Wireless_GUI_0509\test_data_ner\mode1\test2025-05-21-23-37-41sensor.npy"

def load_and_analyze_npy(file_path):
    """加载并分析 NPY 文件"""
    # 加载 NPY 文件
    print(f"正在加载文件: {file_path}")
    data = np.load(file_path, allow_pickle=True).item()
    
    # 打印数据结构
    print("\n数据结构:")
    for key in data.keys():
        if isinstance(data[key], list):
            print(f"{key}: 列表, 长度 = {len(data[key])}")
        else:
            print(f"{key}: {type(data[key])}")
    
    return data

def visualize_accelerometer_data(data):
    """专门可视化加速度数据，使用平滑处理并在一张图上显示"""
    # 检查是否有加速度相关数据
    acc_keys = ['AcclX', 'AcclY', 'AcclZ']
    available_keys = [key for key in acc_keys if key in data and isinstance(data[key], list) and len(data[key]) > 0]
    
    if not available_keys:
        print("警告: 未找到加速度数据")
        return
    
    # 创建图表
    plt.figure(figsize=(14, 8))
    
    # 定义颜色和标签
    colors = ['#FF5733', '#33A8FF', '#33FF57']  # 红、蓝、绿
    labels = {'AcclX': 'AcclX', 'AcclY': 'AcclY', 'AcclZ': 'AcclZ'}
    
    # 平滑参数
    window_length = 51  # 窗口长度必须是奇数
    polyorder = 3  # 多项式阶数
    
    # 绘制加速度数据
    for i, key in enumerate(available_keys):
        # 获取原始数据
        raw_data = np.array(data[key])
        
        # 确保数据长度足够进行平滑处理
        if len(raw_data) > window_length:
            # 应用Savitzky-Golay滤波器进行平滑处理
            smoothed_data = savgol_filter(raw_data, window_length, polyorder)
            
            # 绘制平滑后的数据
            plt.plot(smoothed_data, color=colors[i], linewidth=2.5, label=labels[key])
            
            # 绘制原始数据（半透明）
            plt.plot(raw_data, color=colors[i], linewidth=0.8, alpha=0.3)
        else:
            # 如果数据点太少，无法进行平滑处理，则只绘制原始数据
            plt.plot(raw_data, color=colors[i], linewidth=2, label=labels[key])
    
    # 添加图表标题和标签
    # plt.title('加速度数据可视化', fontsize=16)
    # plt.xlabel('样本索引', fontsize=14)
    plt.ylabel('accl (g)', fontsize=14)
    plt.legend(fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    
    # 美化图表
    plt.tight_layout()
    
    # 保存图表
    output_dir = os.path.dirname(file_path)
    output_file = os.path.join(output_dir, "accelerometer_visualization.png")
    # plt.savefig(output_file, dpi=300)
    print(f"\n加速度图表已保存到: {output_file}")
    
    # 显示图表
    plt.show()

if __name__ == "__main__":
    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 - {file_path}")
    else:
        # 加载并分析数据
        data = load_and_analyze_npy(file_path)
        
        # 只可视化加速度数据
        visualize_accelerometer_data(data)
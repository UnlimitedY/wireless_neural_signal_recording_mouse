import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import os
import matplotlib.colors as mcolors
from scipy import signal  # 添加这一行导入 signal 模块

# 设置 seaborn 样式
sns.set(style="white")  # 使用白色背景
plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
plt.rcParams['font.size'] = 6  # 设置所有字体大小为6

# 文件路径
# lfp
file_path = r"E:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV3\testtt2025-05-30-22-44-37lfp.npy"

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

def normalize_by_column_median(data):
    """对16通道数据进行列中位数归一化"""
    # 将数据转换为 numpy 数组
    data_array = np.array(data)
    
    # 检查输入数据形状
    if data_array.shape[0] != 16:
        raise ValueError(f"输入数组的第一维应为16，当前为{data_array.shape[0]}")
    # 计算每列的中位数
    column_medians = np.median(data_array, axis=0)
    
    # 从每个元素中减去对应列的中位数
    normalized_data = data_array - column_medians[np.newaxis, :]
    
    return normalized_data

def visualize_lfp_data(data, fs=1000):
    """可视化 LFP 数据"""
    # 提取通道数据
    channels = []
    for i in range(16):
        channel_key = f"Channel_{i}"
        if channel_key in data and len(data[channel_key]) > 0:
            channels.append(data[channel_key])
    
    channels_num = len(channels)
    print(f"找到 {channels_num} 个通道")
    if not channels:
        print("未找到通道数据")
        return
    
    # 处理时间戳
    if "TimeStamp" in data and len(data["TimeStamp"]) > 0:
        original_time_stamps = np.array(data["TimeStamp"])
        print(original_time_stamps[0])
        print(f"原始时间戳长度: {len(original_time_stamps)}")
        print(f"通道数据长度: {len(channels[0])}")
        
        # 计算每个通道数据点对应的时间戳
        # 假设时间戳是每4个点记录一次，且采样率为1000Hz
        points_per_timestamp = len(channels[0]) // len(original_time_stamps)
        print(f"每个时间戳对应的数据点数: {points_per_timestamp}")
        
        # 创建完整的时间戳数组
        # 方法1：线性插值
        time_step =   1/fs * 1000
        full_time_stamps = np.zeros(len(channels[0]))
        start_timestamp = original_time_stamps[0] - (points_per_timestamp - 1) * time_step 
        # 对原始时间戳进行插值 注意，timestamp对应的是packet的最后一个点的时间戳
        for i in range(len(original_time_stamps)): # 
            start_idx = i * points_per_timestamp
            end_idx = min((i + 1) * points_per_timestamp, len(full_time_stamps))
            
            # update the time stamp
            for j in range(end_idx - start_idx):
                full_time_stamps[start_idx + j] = start_timestamp + j * time_step
            # determine the start timestamp of next packet
            
            if(i + 1 < len(original_time_stamps)):
                current_time = original_time_stamps[i]
                next_time = original_time_stamps[i + 1]
                if(next_time - current_time) < 6: # 没有丢包
                    start_timestamp = full_time_stamps[end_idx - 1] + time_step
                else: # 丢包了 以丢包记录到的时间戳为新的起始时间戳
                    print(f"丢包了，当前时间戳：{current_time}，下一个时间戳：{next_time}", full_time_stamps[end_idx - 1] , i)
                    start_timestamp = next_time - (points_per_timestamp - 1) * time_step
            else:
                start_timestamp = full_time_stamps[end_idx - 1] 
            # print(full_time_stamps[i])
        
        # 转换为相对时间（秒）
        time_stamps = (full_time_stamps - full_time_stamps[0]) / 1000.0
    else:
        # 如果没有时间戳，创建一个假设的时间轴（1000Hz采样率）
        time_stamps = np.arange(len(channels[0])) / 1000.0

    # 1. 绘制原始数据热图
    plt.figure(figsize=(5, 3))
    
    # 将通道数据转换为数组并转置以便绘制热图
    channel_data = np.array(channels)
    
    # 创建热图
    sns.heatmap(channel_data, cmap="viridis", xticklabels=False, yticklabels=False, cbar=False)
    
    plt.tight_layout()
    
    # 2. 绘制归一化后的数据
    plt.figure(figsize=(5, 3))
    normalized_data = normalize_by_column_median(channel_data) # normalize_by_column_median
    sns.heatmap(normalized_data, cmap="viridis", xticklabels=False, yticklabels=False, cbar=False)
    
    plt.tight_layout()
    
    # 3. 绘制每个通道的时间序列（使用不同颜色的线条和白色背景）
    plt.figure(figsize=(5, 3), facecolor='white')
    
    # 选择要显示的通道数量
    channels_to_show = min(16, len(channels))
    
    # 计算每个通道的垂直偏移量
    y_offset = 1000  # 200uV 的垂直偏移
    
    # 创建一个子图
    ax = plt.subplot(111)
    
    # 移除所有边框和刻度
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    
    # 定义颜色列表 - 使用 tab20 色彩方案获取足够多的颜色
    colors = plt.cm.tab20(np.linspace(0, 1, channels_to_show))
    
    # 绘制所有通道
    for i in range(channels_to_show):
        # 限制数据点数量以提高性能
        # max_points = 30000
        # 修复：使用 numpy 的广播或列表推导式
        offset_data = np.array(channels[i]) + i * y_offset
        plt.plot(time_stamps, offset_data, color="k", linewidth=0.5)
        # 添加通道分隔线
        plt.axhline(y=i*y_offset, color='lightgray', linestyle='--', linewidth=1, alpha=1)
    
    # 添加比例尺
    # 垂直比例尺 (100uV)
    scale_y_pos = 0  # 在第一个通道位置
    plt.plot([0, 0], [scale_y_pos, scale_y_pos + y_offset], 'k-', linewidth=1)
    plt.text(0.1, scale_y_pos + y_offset/2, str(y_offset) + 'μV', va='center')
    
    # 水平比例尺 (5s)
    scale_x_pos = scale_y_pos - y_offset/2
    plt.plot([0, 5], [scale_x_pos, scale_x_pos], 'k-', linewidth=1)
    plt.text(2.5, scale_x_pos - y_offset/4, '5 s', ha='center')
    
    # 设置适当的轴范围
    plt.xlim(0, max(10, max(time_stamps)))
    plt.ylim(-y_offset, channels_to_show * y_offset + y_offset)
    
    plt.tight_layout()
    
    # 4. 绘制通道间相关性
    plt.figure(figsize=(5, 3))
    
    # 计算相关矩阵
    corr_matrix = np.corrcoef(channel_data)
    
    # 绘制相关性热图（无标签和标题）
    sns.heatmap(corr_matrix, cmap="coolwarm", vmin=-1, vmax=1, 
                xticklabels=False, yticklabels=False, annot=False, cbar=False)
    
    plt.tight_layout()
    
    # 5. 绘制功率谱密度 - 所有通道在一个图上
    plt.figure(figsize=(5, 3))
    
    # 创建一个子图
    ax = plt.subplot(111)
    
    # 移除多余的边框
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # 计算并绘制所有通道的功率谱密度
    for i in range(channels_to_show):
        f, Pxx = signal.welch(channels[i], fs, nperseg=1024)
        
        # 限制频率范围到 0-100Hz
        mask = f <= fs/2
        plt.semilogy(f[mask], Pxx[mask], color=colors[i], linewidth=0.8)
    
    plt.tight_layout()
    
    # 保存图表
    output_dir = os.path.dirname(file_path)
    # plt.figure(1).savefig(os.path.join(output_dir, "lfp_heatmap.png"), dpi=300)
    # plt.figure(2).savefig(os.path.join(output_dir, "lfp_normalized.png"), dpi=300)
    # plt.figure(3).savefig(os.path.join(output_dir, "timeseries.pdf"), dpi=300, facecolor='white')
    # # plt.figure(4).savefig(os.path.join(output_dir, "lfp_correlation.png"), dpi=300)
    # plt.figure(5).savefig(os.path.join(output_dir, "psd.pdf"), dpi=300)
    
    print(f"\n图表已保存到: {output_dir}")
    
    # 显示图表
    plt.show()

if __name__ == "__main__":
    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 - {file_path}")
    else:
        # 加载并分析数据
        data = load_and_analyze_npy(file_path)
        
        # 可视化数据
        visualize_lfp_data(data, 1000)
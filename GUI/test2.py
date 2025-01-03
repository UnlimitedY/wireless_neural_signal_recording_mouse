import numpy as np
import matplotlib.pyplot as plt
import  os

#search.py
import os
import sys
import collections as coll

FIFO_list_temp = np.arange(0, 1000)
timestamp_temp = np.arange(0, 1000) * -1
FIFO_list_temp = sorted(FIFO_list_temp, key=lambda x: (timestamp_temp[x]))
print(list(FIFO_list_temp).index(0))

# filr = "test_RawData_0_2024-12-02-16-38-54.npy"
# data = np.load(filr, allow_pickle=True)
# plt.plot(data.item()["Channel_0"])
# plt.plot(data.item()["Channel_15"])
# plt.show()
# print(data.item()["Channel_0"]) 
# DAC_resolution = 1/(int('ffff' ,16)) * 1.225 * 2
# print("sgssh")
# print((float(int('0020' ,16) * DAC_resolution) - 1.225) / 192 * 1000 * 1000)

# tempinde_positve = self.LFP_raw_data[i] > self.saturation_value + i * self.separate_interval
                # self.LFP_raw_data[i][tempinde_positve] = self.saturation_value + i * self.separate_interval

                # tempinde_negative = self.LFP_raw_data[i] < -self.saturation_value + i * self.separate_interval
                # self.LFP_raw_data[i][tempinde_negative] = -self.saturation_value + i * self.separate_interval

# print(len([[1,2] ,[2]]))
# def DAC(x ,raw=True, two_complement=False): 
#     if raw:
#         if(two_complement):
#             if (int(x, 16) < int('8000', 16)):
#                 return int(x, 16)
#             else:
#                 a = int(x, 16) 
#                 return a - 2**(len(x) * 4)
#         else:
#             return int(x ,16) # n


# print(DAC("ffff", raw=True, two_complement=True))
# print(temp_timestamp_mode2, temp_packet_index, packets[-10:])
                    # if((temp_timestamp_mode2 - self.test > 6) or (temp_timestamp_mode2 - self.test < 0) ):
                    #     print(temp_timestamp_mode2 - self.test)
                    #     print(temp_timestamp_mode2, temp_packet_index, packets[-10:])
                    #     if(self.test1 < 3):
                    #         print("packet_num1:", self.test1)
                    #     self.test1 = 0
                    # elif((temp_timestamp_mode2 - self.test <= 6)):
                    #     if(self.test1 < 3):
                    #         print("packet_num2:", self.test1)
                    #     self.test1 = 0
                    # if((temp_timestamp_mode2 - self.test == 0)):
                    #     self.test1 += 1


                    #  if((temp_timestamp_mode2 - self.test > 8) or (temp_timestamp_mode2 - self.test < 0)):
                    #     print(self.test1)
                    #     self.test1 = []
                    #     print("lossPackets:", temp_timestamp_mode2 - self.test)
                    # elif(temp_timestamp_mode2 - self.test != 0):
                    #     if(len(self.test1) < 3):
                    #         # print(self.test1)
                    #         self.test2 += (3 - len(self.test1))
                    #     self.test1 = []
                    # self.test = temp_timestamp_mode2
                    # self.test1.append(temp_timestamp_mode2)
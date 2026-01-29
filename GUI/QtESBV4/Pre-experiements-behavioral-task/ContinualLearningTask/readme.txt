用于研究continual learning castrastic forgetting
声音刺激：
Context===1. 左右方向
Dimension1===2. 声音频率 （8KHz Vs 32KHz， 5 level contast）
Dimension2===3. Click 频率 （16Hz VS 64 Hz， 5 level contrast）

Block-based training（antibias， copy error trials with 60% prob）
【Dimen1】(training + testing) =》【Dimen2】(training + testing) =》
【Randomly interleaved for testing】 =》【Dimen1】.......

Catch trials【random reward】
1. Baseline trials: no sample【THE first useful trial of trial-block】
2. without context trial 【stimulis from two buzzes， 5%】
3. Trials with contast 【Testing protocols， 10%】
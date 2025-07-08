#include "OnlineFilter.h"
/********
 * 
 * 
 */
/****************define**************** */
float scale_factor = RHD2132_ADC_REF_VOLTAGE_v * 2.f / (65536.0f) / RHD2132_ADC_GAIN * 1000000.f;

// Global filter configurations
FilterConfig lowpass_config;
FilterConfig highpass_config;

// Channel filter states
ChannelFilterState channel_states[NUM_CHANNELS] ARM_ALIGN;

// Processing buffers
float32_t input_buffer[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
float32_t lowpass_buffer[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
float32_t decimated_buffer[NUM_CHANNELS * (CHUNK_SIZE/DECIMATION_FACTOR)] ARM_ALIGN;
float32_t highpass_buffer[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
uint16_t mua_output[CHUNK_SIZE/MUA_BIN_SIZE_MODE_3] ARM_ALIGN;

/***************function***************** */
/**
 * 数值安全的饱和函数
 */
static inline float32_t saturate_float32(float32_t value) {
    if (isnan(value) || isinf(value)) {
        return 0.0f;
    }
    if (value > FLOAT32_MAX_SAFE) {
        return FLOAT32_MAX_SAFE;
    }
    if (value < FLOAT32_MIN_SAFE) {
        return FLOAT32_MIN_SAFE;
    }
    return 1;
}


void saturation_protection(float32_t data, int channel, int lowpass){ 
   
    // 检查低通和高通滤波器 的输出是否饱和, 使用抽查的形式
    float status = saturate_float32(data);
    // 如果溢出，清零状态之后重新初始化对应的通道的滤波器
    if(status == 0.0f){
        // overflow
        ChannelFilterState *state = &channel_states[channel];
        if(lowpass){
            memset(state->lp_forward_state, 0, sizeof(state->lp_forward_state));
            arm_biquad_cascade_df2T_init_f32(
                &state->lowpass_forward,
                lowpass_config.num_stages,
                lowpass_config.coeffs,
                state->lp_forward_state
            );
        }else{
            memset(state->hp_state, 0, sizeof(state->hp_state));
            arm_biquad_cascade_df2T_init_f32(
                &state->highpass,
                highpass_config.num_stages,
                highpass_config.coeffs,
                state->hp_state
            );
        }
    }else{
        // TODO
    }
}


void convert_rhd2132_samples(u16_t* adc_data, float_t* float_data, uint32_t num_samples, float32_t filter_scale,  bool inttofloat) {
    // 所有的 filter的放缩都是在输入开始放缩，再传输数据出去的时候还原
    // 通用优化路径 (使用循环展开)
    uint32_t i = 0;
    const uint32_t unroll_count = num_samples & ~0x3; // 4的倍数
    
    if(inttofloat){
        // 注意这里需要对RHD的数据进行前后倒转一下
        swap_bytes_builtin(adc_data, num_samples);
        // convert to float
        // arm_q15_to_float((q15_t *)adc_data, float_data, num_samples);
        // 4次循环展开 转为uV
        for (; i < unroll_count; i += 4) {
            float_data[i]   = ((float)(adc_data[i])   *   scale_factor - RHD2132_ADC_REF_VOLTAGE) * filter_scale;
            float_data[i+1] = ((float)(adc_data[i+1])  * scale_factor - RHD2132_ADC_REF_VOLTAGE) * filter_scale;
            float_data[i+2] = ((float)(adc_data[i+2])   * scale_factor - RHD2132_ADC_REF_VOLTAGE) * filter_scale;
            float_data[i+3] = ((float)(adc_data[i+3])   * scale_factor - RHD2132_ADC_REF_VOLTAGE) * filter_scale;
        }
        // 处理剩余样本
        for (; i < num_samples; i++) {
            float_data[i]   = ((float)(float_data[i])   * scale_factor - RHD2132_ADC_REF_VOLTAGE) * filter_scale;
        }
    }else{
        for (; i < unroll_count; i += 4) {
            adc_data[i]   = (uint16_t)((float_data[i] / filter_scale + RHD2132_ADC_REF_VOLTAGE) / scale_factor );
            adc_data[i+1] = (uint16_t)((float_data[i+1] / filter_scale + RHD2132_ADC_REF_VOLTAGE) / scale_factor);
            adc_data[i+2] = (uint16_t)((float_data[i+2] / filter_scale + RHD2132_ADC_REF_VOLTAGE) / scale_factor);
            adc_data[i+3] = (uint16_t)((float_data[i+3] / filter_scale + RHD2132_ADC_REF_VOLTAGE) / scale_factor);
        }
        // 处理剩余样本
        for (; i < num_samples; i++) {
            adc_data[i]   = (uint16_t)((float_data[i] / filter_scale + RHD2132_ADC_REF_VOLTAGE) / scale_factor );
        }
        // 直接输出 转换为uV的数值
        // arm_float_to_q15(float_data, (q15_t *)adc_data, num_samples);
        
    }
}

/**
 * Calculate Butterworth filter coefficients
 * @param config: Filter configuration structure
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_butterworth_coeffs(FilterConfig *config) {
    if (config->order != IIR_ORDER_lowpass || config->cutoff_freq != IIR_CUTOFF_lowpass) {
        return ARM_MATH_ARGUMENT_ERROR;
    }
    config->num_stages = config->order / 2;
    
    // coeffi 625
    config->coeffs[0] = 1.0f;     // b0
	config->coeffs[1] = 2.0f; // b1
	config->coeffs[2] = 1.0f;     // b2
	config->coeffs[3] = 1.700964331943525920110005245078355073929f; // a1
	config->coeffs[4] = -0.788499739815297973066776648920495063066f; // a2

	config->coeffs[5] = 1.00000000f;     // b0
	config->coeffs[6] = 2.0000000f; // b1
	config->coeffs[7] = 1.0f;     // b2
	config->coeffs[8] = 1.479674216931193386770360120863188058138f; // a1
	config->coeffs[9] = -0.555821543282489005655122582538751885295f; // a2

    config->gain = 0.021883851967943023647533706821377563756f * 0.019036831587823873496168047836363257375f;
    return ARM_MATH_SUCCESS;
}

/**
 * Calculate high-pass Butterworth filter coefficients
 * @param config: Filter configuration structure
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_highpass_butterworth_coeffs(FilterConfig *config) {
     if (config->order != IIR_ORDER_highpass || config->cutoff_freq != IIR_CUTOFF_highpass) {
        return ARM_MATH_ARGUMENT_ERROR;
    }
    
    config->num_stages = config->order / 2;
    
    config->coeffs[0] = 1.0f;     // b0
	config->coeffs[1] = -2.0f; // b1
	config->coeffs[2] = 1.0f;     // b2
	config->coeffs[3] = 1.78743251795648472324273825506679713726f; // a1
	config->coeffs[4] = -0.807949591420913271200276994932210072875f; // a2

	config->gain = 0.898845527344349526366329428128665313125f;
    
    return ARM_MATH_SUCCESS;
}

/**
 * Initialize low-pass filter with specified order and cutoff frequency
 * @param order: Filter order (must be even)
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_lowpass_filter(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate) {
    lowpass_config.order = order;
    lowpass_config.cutoff_freq = cutoff_freq;
    lowpass_config.sampling_rate = sampling_rate;
    
    arm_status status = calculate_butterworth_coeffs(&lowpass_config);
    if (status != ARM_MATH_SUCCESS) {
        return status;
    }
    
    // Initialize filter instances for all channels
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        ChannelFilterState *state = &channel_states[ch];
        memset(state->lp_forward_state, 0, sizeof(state->lp_forward_state));
        state->lowpass_gain = lowpass_config.gain;
        
        // Initialize forward filter
        arm_biquad_cascade_df2T_init_f32(
            &state->lowpass_forward,
            lowpass_config.num_stages,
            lowpass_config.coeffs,
            state->lp_forward_state
        );
    }
    
    return ARM_MATH_SUCCESS;
}

/**
 * Initialize high-pass filter with specified order and cutoff frequency
 * @param order: Filter order (must be even)
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_highpass_filter(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate) {
    highpass_config.order = order;
    highpass_config.cutoff_freq = cutoff_freq;
    highpass_config.sampling_rate = sampling_rate;
    
    arm_status status = calculate_highpass_butterworth_coeffs(&highpass_config);
    if (status != ARM_MATH_SUCCESS) {
        return status;
    }
    
    // Initialize filter instances for all channels
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        ChannelFilterState *state = &channel_states[ch];
        memset(state->hp_state, 0, sizeof(state->hp_state));
        state->highpass_gain = highpass_config.gain;
        arm_biquad_cascade_df2T_init_f32(
            &state->highpass,
            highpass_config.num_stages,
            highpass_config.coeffs,
            state->hp_state
        );
        
        // Initialize spike detection parameters
        state->last_spike_time = -MIN_ISI;
        state->threshold = 50.0f; // Default threshold
    }
    
    return ARM_MATH_SUCCESS;
}

/**
 * Set spike detection threshold for a specific channel
 * @param channel: Channel index
 * @param threshold: Spike detection threshold
 */
void set_spike_threshold(uint8_t channel, float32_t threshold) {
    if (channel < NUM_CHANNELS) {
        channel_states[channel].threshold = threshold * Filter_scale;
    }
}


/**
 * Decimate signal by integer factor using ARM CMSIS DSP
 * @param input: Input signal
 * @param output: Output decimated signal
 * @param input_length: Input signal length
 * @param factor: Decimation factor
 * @return: Output signal length
 */
static inline uint32_t decimate_signal_arm(const float32_t *input, float32_t *output, 
                                          uint32_t input_length, uint32_t factor) {
    uint32_t output_length = input_length / factor;
    for (uint32_t i = 0; i < output_length; i++) {
        output[i] = input[i * factor];
    }
    return output_length;
}

/**
 * ARM CMSIS DSP optimized spike detection with MUA extraction
 * @param signal: High-pass filtered signal
 * @param mua_data: Output MUA data
 * @param length: Signal length
 * @param channel: Channel index
 * @return: Number of detected spikes
 */
static uint32_t detect_spikes_and_extract_mua(const float32_t *signal, uint16_t *mua_data, 
                                             uint32_t length, uint8_t channel) {
    ChannelFilterState *state = &channel_states[channel];
    uint32_t spike_count = 0;
    float32_t neg_threshold = -state->threshold;
    
    // Clear MUA bins for this processing chunk
    uint32_t num_bins = length / MUA_BIN_SIZE_MODE_3;
    // reset last spike_time
    state->last_spike_time = -MIN_ISI;
    
    for (uint32_t i = SPIKE_WINDOW; i < length - SPIKE_WINDOW; i++) {
        // Detect negative-going spikes
        if (signal[i] < neg_threshold && 
            signal[i] < signal[i-1] && 
            signal[i] < signal[i+1] &&
            (int32_t)i - state->last_spike_time >= MIN_ISI) {
            
            // Verify it's a local minimum in the window
            bool is_minimum = true;
            for (int j = -SPIKE_WINDOW; j <= SPIKE_WINDOW; j++) {
                if (j != 0 && signal[i] >= signal[i + j]) {
                    is_minimum = false;
                    break;
                }
            }
            
            if (is_minimum) {
                spike_count++;
                state->last_spike_time = i;
                
                // Add to MUA bin
                uint32_t bin = i / MUA_BIN_SIZE_MODE_3;
                if (bin < num_bins) {
                    mua_data[bin] |= (1 << channel);
                }
            }
        }
    }
    return spike_count;
}

/**
 * Main neural signal processing function
 * @param input_data: Input neural data [channels x samples]
 * @param samples_per_channel: Number of samples per channel
 * @param lowpass_output: Output low-pass filtered and decimated data
 * @param highpass_output: Output high-pass filtered data
 * @param mua_data: Output MUA data
 * @return: Number of output samples after decimation
 */
uint32_t process_neural_signals(const float32_t *input_data, uint32_t samples_per_channel,
                               float32_t *lowpass_output, float32_t *highpass_output,
                               uint16_t *mua_data) {
    // Clear MUA output
    uint32_t mua_bins = samples_per_channel / MUA_BIN_SIZE_MODE_3;
    memset(mua_data, 0, mua_bins * sizeof(uint16_t));
    
    uint32_t decimated_length = samples_per_channel / DECIMATION_FACTOR;
    
    // Process each channel
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        const float32_t *ch_input = &input_data[ch * samples_per_channel];
        ChannelFilterState *state = &channel_states[ch];
        
        // === LOW-PASS FILTERING ===
        // Forward filtering
        arm_biquad_cascade_df2T_f32(
            &state->lowpass_forward,
            ch_input,
            lowpass_buffer,
            samples_per_channel
        );

        // Decimate to target sampling rate
        decimate_signal_arm(lowpass_buffer, 
                           &lowpass_output[ch * decimated_length],
                           samples_per_channel, 
                           DECIMATION_FACTOR);
        
        // recover data by multiply filter gain
        // low pass : only decimate data
        for(int i=0; i<decimated_length; i++){
                lowpass_output[ch * decimated_length + i] *= state->lowpass_gain;
        }
        
        // === HIGH-PASS FILTERING ===
        
        arm_biquad_cascade_df2T_f32(
            &state->highpass,
            ch_input,
            &highpass_output[ch * samples_per_channel],
            samples_per_channel
        );

        // recover data by multiply filter gain
        for(int i=0; i<samples_per_channel; i++){
                highpass_output[ch * samples_per_channel + i] *= state->highpass_gain;
        }
        
        // === SPIKE DETECTION AND MUA EXTRACTION ===
        detect_spikes_and_extract_mua(
            &highpass_output[ch * samples_per_channel],
            mua_data,
            samples_per_channel,
            ch
        );
    }
    return decimated_length;
}

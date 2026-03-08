#include "OnlineFilter.h"
/********
 * 
 * 
 */
/****************define**************** */
float scale_factor = RHD2132_ADC_REF_VOLTAGE_v * 2.f / (65536.0f) / RHD2132_ADC_GAIN * 1000000.f;

// Global filter configurations
FilterConfig LFPlowpass_config;
FilterConfig ESAlowpass_config;
FilterConfig ESAhighpass_config;

// Channel filter states
ChannelFilterState channel_states[NUM_CHANNELS] ARM_ALIGN;

// Processing buffers
float32_t input_buffer[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
float32_t lowpass_buffer_LFP[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
float32_t decimated_buffer_LFP[NUM_CHANNELS * MODE3_DECIMATED_SAMPLES_PER_CHANNEL] ARM_ALIGN;
float32_t lowpass_buffer_ESA[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
float32_t highpass_buffer_ESA[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
float32_t rectified_buffer_ESA[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
float32_t decimated_buffer_ESA[NUM_CHANNELS * MODE3_DECIMATED_SAMPLES_PER_CHANNEL] ARM_ALIGN;
float32_t reref_buffer_ESA[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
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
            memset(state->lp_forward_state_LFP, 0, sizeof(state->lp_forward_state_LFP));
            arm_biquad_cascade_df2T_init_f32(
                &state->lowpass_forward_LFP,
                LFPlowpass_config.num_stages,
                LFPlowpass_config.coeffs,
                state->lp_forward_state_LFP
            );
        }else{
            memset(state->hp_state_ESA, 0, sizeof(state->hp_state_ESA));
            arm_biquad_cascade_df2T_init_f32(
                &state->highpass_ESA,       
                ESAhighpass_config.num_stages,
                ESAhighpass_config.coeffs,
                state->hp_state_ESA
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
            float_data[i]   = ((float)(adc_data[i])   * scale_factor - RHD2132_ADC_REF_VOLTAGE) * filter_scale;
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
 * Calculate Butterworth filter coefficients for LFP (2nd order, 250Hz @ 12.5kHz)
 * @param config: Filter configuration structure
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_butterworth_coeffs_LFP(FilterConfig *config) {
    if (config->order != IIR_ORDER_lowpass_LFP || config->cutoff_freq != IIR_CUTOFF_lowpass_LFP) {
        return ARM_MATH_ARGUMENT_ERROR;
    }
    config->num_stages = config->order / 2;
    
    // 2nd order Butterworth lowpass filter coefficients for 250Hz @ 12.5kHz sampling rate  Group delay Max 1ms
    // Calculated using bilinear transform
    config->coeffs[0] = 1.0f;     // b0
	config->coeffs[1] = 2.0f;     // b1
	config->coeffs[2] = 1.0f;     // b2
	config->coeffs[3] = 1.822694925196308268766642868285998702049f;    // a1
	config->coeffs[4] = -0.837181651256022618667884671594947576523f;     // a2

    config->gain = 0.003621681514928642119099944096660692594f; 
    return ARM_MATH_SUCCESS;
}

/**
 * Calculate Butterworth filter coefficients for ESA lowpass (1st order, 12Hz @ 12.5kHz)
 * @param config: Filter configuration structure
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_butterworth_coeffs_ESA(FilterConfig *config) {
    if (config->order != IIR_ORDER_lowpass_ESA || config->cutoff_freq != IIR_CUTOFF_lowpass_ESA) {
        return ARM_MATH_ARGUMENT_ERROR;
    }
    
    config->num_stages = 1; // 1st order filter
    
    // 1st order Butterworth lowpass filter coefficients for 150Hz @ 12.5kHz sampling rate ； Group delay Max 1ms
    // Calculated using bilinear transform: H(z) = (b0 + b1*z^-1) / (1 + a1*z^-1)
    config->coeffs[0] = 1.0f;     // b0
	config->coeffs[1] = 1.0f;     // b1
	config->coeffs[2] = 0.0f;                   // b2 (not used for 1st order)
	config->coeffs[3] = 0.927307768331003257067379763611825183034f;    // a1
	config->coeffs[4] = 0.0f;                   // a2 (not used for 1st order)

    config->gain = 0.036346115834498420038567445544686052017f; 
    return ARM_MATH_SUCCESS;
}

/**
 * Calculate high-pass Butterworth filter coefficients for ESA (1st order, 250Hz @ 12.5kHz)
 * @param config: Filter configuration structure
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_highpass_butterworth_coeffs_ESA(FilterConfig *config) {
     if (config->order != IIR_ORDER_highpass_ESA || config->cutoff_freq != IIR_CUTOFF_highpass_ESA) {
        return ARM_MATH_ARGUMENT_ERROR;
    }
    
    config->num_stages = 1; // 1st order filter
    
    // 1st order Butterworth highpass filter coefficients for 250Hz @ 12.5kHz sampling rate
    // Calculated using bilinear transform: H(z) = (b0 + b1*z^-1) / (1 + a1*z^-1)
    config->coeffs[0] = 1.0f;     // b0
	config->coeffs[1] = -1.0f;    // b1
	config->coeffs[2] = 0.0f;                   // b2 (not used for 1st order)
	config->coeffs[3] = 0.881618592363189068628059885668335482478f;    // a1
	config->coeffs[4] = 0.0f;                   // a2 (not used for 1st order)

	config->gain = 0.940809296181594478802878711576340720057f; 
    
    return ARM_MATH_SUCCESS;
}

/**
 * Initialize low-pass filter for LFP (2nd order, 250Hz)
 * @param order: Filter order (must be even)
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_lowpass_filter_LFP(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate) {
    LFPlowpass_config.order = order;
    LFPlowpass_config.cutoff_freq = cutoff_freq;
    LFPlowpass_config.sampling_rate = sampling_rate;
    
    arm_status status = calculate_butterworth_coeffs_LFP(&LFPlowpass_config);
    if (status != ARM_MATH_SUCCESS) {
        return status;
    }
    
    // Initialize filter instances for all channels
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        ChannelFilterState *state = &channel_states[ch];
        memset(state->lp_forward_state_LFP, 0, sizeof(state->lp_forward_state_LFP));
        state->lowpass_gain_LFP = LFPlowpass_config.gain;
        
        // Initialize forward filter
        arm_biquad_cascade_df2T_init_f32(
            &state->lowpass_forward_LFP,
            LFPlowpass_config.num_stages,
            LFPlowpass_config.coeffs,
            state->lp_forward_state_LFP
        );
    }
    
    return ARM_MATH_SUCCESS;
}

/**
 * Initialize low-pass filter for ESA (1st order, 12Hz)
 * @param order: Filter order
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_lowpass_filter_ESA(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate) {
    ESAlowpass_config.order = order;
    ESAlowpass_config.cutoff_freq = cutoff_freq;
    ESAlowpass_config.sampling_rate = sampling_rate;
    
    arm_status status = calculate_butterworth_coeffs_ESA(&ESAlowpass_config);
    if (status != ARM_MATH_SUCCESS) {
        return status;
    }
    
    // Initialize filter instances for all channels
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        ChannelFilterState *state = &channel_states[ch];
        memset(state->lp_forward_state_ESA, 0, sizeof(state->lp_forward_state_ESA));
        state->lowpass_gain_ESA = ESAlowpass_config.gain;
        
        // Initialize ESA lowpass filter
        arm_biquad_cascade_df2T_init_f32(
            &state->lowpass_forward_ESA,
            ESAlowpass_config.num_stages,
            ESAlowpass_config.coeffs,
            state->lp_forward_state_ESA
        );
    }
    
    return ARM_MATH_SUCCESS;
}

/**
 * Initialize high-pass filter for ESA (1st order, 250Hz)
 * @param order: Filter order
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_highpass_filter_ESA(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate) {
    ESAhighpass_config.order = order;
    ESAhighpass_config.cutoff_freq = cutoff_freq;
    ESAhighpass_config.sampling_rate = sampling_rate;
    
    arm_status status = calculate_highpass_butterworth_coeffs_ESA(&ESAhighpass_config);
    if (status != ARM_MATH_SUCCESS) {
        return status;
    }
    
    // Initialize filter instances for all channels
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        ChannelFilterState *state = &channel_states[ch];
        memset(state->hp_state_ESA, 0, sizeof(state->hp_state_ESA));
        state->highpass_gain_ESA = ESAhighpass_config.gain;
        arm_biquad_cascade_df2T_init_f32(
            &state->highpass_ESA,
            ESAhighpass_config.num_stages,
            ESAhighpass_config.coeffs,
            state->hp_state_ESA
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
 * Resample signal from 12.5kHz to 1kHz
 * @param input: Input signal
 * @param output: Output resampled signal
 * @param input_length: Input signal length
 * @return: Output signal length
 */
static inline uint32_t resample_signal_12500_to_1000(const float32_t *input, float32_t *output,
                                                     uint32_t input_length) {
    uint32_t output_length = (input_length * RESAMPLE_NUMERATOR) / RESAMPLE_DENOMINATOR;
    for (uint32_t i = 0; i < output_length; i++) {
        uint32_t position_num = i * RESAMPLE_DENOMINATOR;
        uint32_t base_idx = position_num / RESAMPLE_NUMERATOR;
        if ((position_num & 0x1U) == 0U) {
            output[i] = input[base_idx];
        } else {
            output[i] = 0.5f * (input[base_idx] + input[base_idx + 1]);
        }
    }
    return output_length;
}

/**
 * Optimized spike detection with MUA extraction for Mode 3
 * Features: Adaptive thresholding, noise suppression, and efficient peak detection
 * @param signal: High-pass filtered signal (1st order 250Hz)
 * @param mua_data: Output MUA data
 * @param length: Signal length
 * @param channel: Channel index
 * @return: Number of detected spikes
 */
static inline void detect_spikes_and_extract_mua(const float32_t *signal, uint16_t *mua_data, 
                                             uint32_t length, uint8_t channel) { // 30 points 
    ChannelFilterState *state = &channel_states[channel];
    float32_t neg_threshold = -state->threshold;
    // Clear MUA bins for this processing chunk
    uint16_t num_bins = length / MUA_BIN_SIZE_MODE_3; // 3
    uint16_t SPIKE_WINDOW_half = SPIKE_WINDOW/2; // 1
    uint16_t bin = 0;
    state->last_spike_time -= length; // re-index the spike time according to global singal stream
    // Enhanced spike detection with noise suppression
    for (uint32_t i = SPIKE_WINDOW_half; i < length - SPIKE_WINDOW_half; i++) { // 1 -> 28
        // Primary spike detection criteria
        if (signal[i] < neg_threshold && 
            signal[i] < signal[i-1] && 
            signal[i] < signal[i+1] &&
            (int32_t)i - state->last_spike_time >= MIN_ISI) {
            state->last_spike_time = i;
            
            // Add to MUA bin with channel-specific bit
            bin = i / MUA_BIN_SIZE_MODE_3; // 0, 1 ,2
            if (bin < num_bins) {
                mua_data[bin] |= (1 << channel);
            }
        }
    }
}

#define SWAP_SORT(a, b)            \
    do {                           \
        if ((a) > (b)) {           \
            float32_t t = (a);     \
            (a) = (b);             \
            (b) = t;               \
        }                          \
    } while (0)

static inline float32_t calculate_median_16(float32_t *values) { 
    float32_t x0  = values[0];
    float32_t x1  = values[1];
    float32_t x2  = values[2];
    float32_t x3  = values[3];
    float32_t x4  = values[4];
    float32_t x5  = values[5];
    float32_t x6  = values[6];
    float32_t x7  = values[7];
    float32_t x8  = values[8];
    float32_t x9  = values[9];
    float32_t x10 = values[10];
    float32_t x11 = values[11];
    float32_t x12 = values[12];
    float32_t x13 = values[13];
    float32_t x14 = values[14];
    float32_t x15 = values[15];

    SWAP_SORT(x0, x13);  SWAP_SORT(x1, x12);  SWAP_SORT(x2, x15);  SWAP_SORT(x3, x14);
    SWAP_SORT(x4, x8);   SWAP_SORT(x5, x6);   SWAP_SORT(x7, x11);  SWAP_SORT(x9, x10);

    SWAP_SORT(x0, x5);   SWAP_SORT(x1, x7);   SWAP_SORT(x2, x9);   SWAP_SORT(x3, x4);
    SWAP_SORT(x6, x13);  SWAP_SORT(x8, x14);  SWAP_SORT(x10, x15); SWAP_SORT(x11, x12);

    SWAP_SORT(x0, x1);   SWAP_SORT(x2, x3);   SWAP_SORT(x4, x5);   SWAP_SORT(x6, x8);
    SWAP_SORT(x7, x9);   SWAP_SORT(x10, x11); SWAP_SORT(x12, x13); SWAP_SORT(x14, x15);

    SWAP_SORT(x0, x2);   SWAP_SORT(x1, x3);   SWAP_SORT(x4, x10);  SWAP_SORT(x5, x11);
    SWAP_SORT(x6, x7);   SWAP_SORT(x8, x9);   SWAP_SORT(x12, x14); SWAP_SORT(x13, x15);

    SWAP_SORT(x1, x2);   SWAP_SORT(x3, x12);  SWAP_SORT(x4, x6);   SWAP_SORT(x5, x7);
    SWAP_SORT(x8, x10);  SWAP_SORT(x9, x11);  SWAP_SORT(x13, x14);

    SWAP_SORT(x1, x4);   SWAP_SORT(x2, x6);   SWAP_SORT(x5, x8);
    SWAP_SORT(x7, x10);  SWAP_SORT(x9, x13);  SWAP_SORT(x11, x14);

    SWAP_SORT(x2, x4);   SWAP_SORT(x3, x6);   SWAP_SORT(x9, x12);  SWAP_SORT(x11, x13);

    SWAP_SORT(x3, x5);   SWAP_SORT(x6, x8);   SWAP_SORT(x7, x9);   SWAP_SORT(x10, x12);

    SWAP_SORT(x3, x4);   SWAP_SORT(x5, x6);   SWAP_SORT(x7, x8);   SWAP_SORT(x9, x10);
    SWAP_SORT(x11, x12);

    SWAP_SORT(x6, x7);   SWAP_SORT(x8, x9);

    return 0.5f * (x7 + x8);
}

static inline float32_t calculate_median_16_safe(const float32_t *values) {
    float32_t sorted_values[NUM_CHANNELS] ARM_ALIGN;
    for (uint32_t i = 0; i < NUM_CHANNELS; i++) {
        sorted_values[i] = values[i];
    }
    for (uint32_t i = 1; i < NUM_CHANNELS; i++) {
        float32_t key = sorted_values[i];
        int32_t j = (int32_t)i - 1;
        while (j >= 0 && sorted_values[j] > key) {
            sorted_values[j + 1] = sorted_values[j];
            j--;
        }
        sorted_values[j + 1] = key;
    }
    return 0.5f * (sorted_values[(NUM_CHANNELS / 2) - 1] + sorted_values[NUM_CHANNELS / 2]);
}

static inline void apply_common_median_reference(const float32_t *input_data,
                                                 float32_t *output_data,
                                                 uint32_t samples_per_channel) {
    float32_t sample_values[NUM_CHANNELS] ARM_ALIGN;
    for (uint32_t sample_idx = 0; sample_idx < samples_per_channel; sample_idx++) {
        for (uint32_t ch = 0; ch < NUM_CHANNELS; ch++) {
            sample_values[ch] = input_data[ch * samples_per_channel + sample_idx];
        }
        float32_t median;
        if (mode3_esa_reref_enable == MODE3_ESA_REREF_FAST_MEDIAN) {
            median = calculate_median_16(sample_values);
        } else {
            median = calculate_median_16_safe(sample_values);
        }
        for (uint32_t ch = 0; ch < NUM_CHANNELS; ch++) {
            output_data[ch * samples_per_channel + sample_idx] =
                input_data[ch * samples_per_channel + sample_idx] - median;
        }
    }
}

/**
 * Main neural signal processing function for Mode 3 (LFP, MUA, ESA)
 * @param input_data: Input neural data [channels x samples] at 12.5kHz
 * @param samples_per_channel: Number of samples per channel
 * @param lfp_output: Output LFP data (2nd order lowpass 250Hz + resample to 1kHz)
 * @param mua_data: Output MUA data (spike detection on 1st order highpass 250Hz)
 * @param esa_output: Output ESA data (1st order highpass 250Hz -> rectify -> 1st order lowpass 12Hz + resample to 1kHz)
 * @return: Number of output samples after resampling for LFP and ESA
 */
uint32_t process_neural_signals_mode3(const float32_t *input_data, uint32_t samples_per_channel,
                                     float32_t *lfp_output, uint16_t *mua_data, float32_t *esa_output) {
    // Clear MUA output
    uint32_t mua_bins = samples_per_channel / MUA_BIN_SIZE_MODE_3;
    memset(mua_data, 0, mua_bins * sizeof(uint16_t));
    
    uint32_t decimated_length = process_lfp_lowpass_decimate(input_data, samples_per_channel, lfp_output);
    const float32_t *esa_input = input_data;
    if (mode3_esa_reref_enable != MODE3_ESA_REREF_DISABLED) {
        apply_common_median_reference(input_data, reref_buffer_ESA, samples_per_channel);
        esa_input = reref_buffer_ESA;
    }
    
    // Process each channel
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        const float32_t *ch_esa_input = &esa_input[ch * samples_per_channel];
        ChannelFilterState *state = &channel_states[ch];
        
        // =============================== HIGH-PASS FILTERING for MUA and ESA: 1st order IIR highpass 250Hz ===
        arm_biquad_cascade_df2T_f32(
            &state->highpass_ESA,
            ch_esa_input,
            &highpass_buffer_ESA[ch * samples_per_channel],
            samples_per_channel
        );

        // Apply highpass filter gain
        for(int i = 0; i < samples_per_channel; i++){
            highpass_buffer_ESA[ch * samples_per_channel + i] *= state->highpass_gain_ESA;
        }
        
        // // === MUA PROCESSING: Spike detection on high-pass filtered data === TODO 这里启动会导致滤波数据失真，可能是达到了cpu的处理速度极限
        // detect_spikes_and_extract_mua(
        //     &highpass_buffer_ESA[ch * samples_per_channel],
        //     mua_data,
        //     samples_per_channel,
        //     ch
        // );
        
        // === ESA PROCESSING: Rectification + 1st order lowpass 150Hz + resample to 1kHz ===
        // Rectification (absolute value)
        for(int i = 0; i < samples_per_channel; i++){
            rectified_buffer_ESA[ch * samples_per_channel + i] = fabsf(highpass_buffer_ESA[ch * samples_per_channel + i]);
        }
        
        // ESA lowpass filtering: 1st order IIR lowpass 150Hz
        arm_biquad_cascade_df2T_f32(
            &state->lowpass_forward_ESA,
            &rectified_buffer_ESA[ch * samples_per_channel],
            &lowpass_buffer_ESA[ch * samples_per_channel],
            samples_per_channel
        );
        
        // Resample ESA to target sampling rate (1kHz)
        resample_signal_12500_to_1000(&lowpass_buffer_ESA[ch * samples_per_channel],
                                      &esa_output[ch * decimated_length],
                                      samples_per_channel);
        
        // Apply ESA filter gain
        for(int i = 0; i < decimated_length; i++){
            esa_output[ch * decimated_length + i] *= state->lowpass_gain_ESA;
        }
    }
    return decimated_length;
}

uint32_t process_lfp_lowpass_decimate(const float32_t *input_data, uint32_t samples_per_channel,
                                     float32_t *lfp_output) {
    if (samples_per_channel > MAX_SAMPLES_PER_CHANNEL || samples_per_channel == 0) {
        return 0;
    }

    float32_t channel_lfp_buffer[MAX_SAMPLES_PER_CHANNEL] ARM_ALIGN;
    uint32_t decimated_length = (samples_per_channel * RESAMPLE_NUMERATOR) / RESAMPLE_DENOMINATOR;

    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
        const float32_t *ch_input = &input_data[ch * samples_per_channel];
        ChannelFilterState *state = &channel_states[ch];

        arm_biquad_cascade_df2T_f32(
            &state->lowpass_forward_LFP,
            ch_input,
            channel_lfp_buffer,
            samples_per_channel
        );

        resample_signal_12500_to_1000(channel_lfp_buffer,
                                      &lfp_output[ch * decimated_length],
                                      samples_per_channel);

        for (uint32_t i = 0; i < decimated_length; i++) {
            lfp_output[ch * decimated_length + i] *= state->lowpass_gain_LFP;
        }
    }
    return decimated_length;
}

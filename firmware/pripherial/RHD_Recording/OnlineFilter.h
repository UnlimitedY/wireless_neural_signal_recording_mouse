/*
 * ARM CMSIS DSP Optimized Neural Signal Processing
 * - Utilizes ARM CMSIS DSP library for maximum performance
 * - Multi-stage filtering with decimation (3 stages)
 * - SIMD optimizations for ARM Cortex-M processors
 * - Memory-aligned data structures for cache efficiency
 */
#ifndef OnlineFilter_h
#define OnlineFilter_h

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#include "RHDRecording.h"
#include "arm_math.h"
#define FLOAT32_MAX_SAFE 1e6f      
#define FLOAT32_MIN_SAFE -1e6f 
#define Filter_scale 1.0f // 给所有输出filer的值在转为uV后乘以 0.1

#define ORIGINAL_FS 12500    // Original sampling rate 10kHz
#define TARGET_FS 1250       // Target sampling rate after low-pass filtering
#define DECIMATION_FACTOR 10 // 10kHz -> 1kHz
#define MAX_FILTER_ORDER 4   // Maximum filter order

// Spike detection parameters
#define MIN_ISI 10           // Minimum inter-spike interval (samples)
#define SPIKE_WINDOW 3       // Spike detection window size
#define MUA_BIN_SIZE_MODE_3 10      // MUA binning size (samples)

#define IIR_ORDER_lowpass_LFP 2          // IIR filter order for LFP
#define IIR_ORDER_lowpass_ESA 1          // IIR filter order for ESA
#define IIR_ORDER_highpass_ESA 1         // IIR filter order for ESA

#define IIR_CUTOFF_lowpass_LFP 250.0f          // IIR filter cutoff 相位延迟 最大1ms （1250 Hz 采样）
#define IIR_CUTOFF_lowpass_ESA 12.0f          // IIR filter cutoff
#define IIR_CUTOFF_highpass_ESA 250.0f          // IIR filter cutoff

// Memory alignment for ARM NEON/SIMD
#define ARM_ALIGN __attribute__((aligned(16)))

#define RHD2132_ADC_REF_VOLTAGE_v   1.225f    // 参考电压 
#define RHD2132_ADC_GAIN    192.f      // 16位ADC
#define RHD2132_ADC_REF_VOLTAGE    RHD2132_ADC_REF_VOLTAGE_v / RHD2132_ADC_GAIN * 1000000.f

extern float scale_factor; // uv

// Filter configuration structure
typedef struct {
    uint8_t order;           // Filter order
    float32_t cutoff_freq;   // Cutoff frequency in Hz
    float32_t sampling_rate; // Sampling rate in Hz
    float32_t coeffs[MAX_FILTER_ORDER * 5]; // Biquad coefficients [b0,b1,b2,a1,a2] per stage
    uint8_t num_stages;      // Number of biquad stages
    // filter gain
    float32_t gain; 
} FilterConfig;

// Filter state structure for each channel
typedef struct {
    arm_biquad_casd_df1_inst_f32 lowpass_forward_LFP;   // Forward low-pass filter

    arm_biquad_casd_df1_inst_f32 lowpass_forward_ESA;   // Forward low-pass filter
    arm_biquad_casd_df1_inst_f32 highpass_ESA;          // High-pass filter
    // filter gain
    float32_t lowpass_gain_LFP;
    float32_t lowpass_gain_ESA;
    float32_t highpass_gain_ESA;
    
    // State buffers
    float32_t lp_forward_state_LFP[MAX_FILTER_ORDER * 2] ARM_ALIGN;
    float32_t lp_forward_state_ESA[MAX_FILTER_ORDER * 2] ARM_ALIGN;
    float32_t hp_state_ESA[MAX_FILTER_ORDER * 2] ARM_ALIGN;
    
    // Spike detection state
    int32_t last_spike_time;
    float32_t threshold;
} ChannelFilterState;

// Global filter configurations
extern FilterConfig LFPlowpass_config;
extern FilterConfig ESAlowpass_config;
extern FilterConfig ESAhighpass_config;

// Channel filter states
extern ChannelFilterState channel_states[NUM_CHANNELS] ARM_ALIGN;

// Processing buffers
extern float32_t input_buffer[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;

extern float32_t lowpass_buffer_LFP[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
extern float32_t decimated_buffer_LFP[NUM_CHANNELS * (CHUNK_SIZE/DECIMATION_FACTOR)] ARM_ALIGN;

extern float32_t lowpass_buffer_ESA[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
extern float32_t highpass_buffer_ESA[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
extern float32_t rectified_buffer_ESA[NUM_CHANNELS * CHUNK_SIZE] ARM_ALIGN;
extern float32_t decimated_buffer_ESA[NUM_CHANNELS * (CHUNK_SIZE/DECIMATION_FACTOR)] ARM_ALIGN;

extern uint16_t mua_output[CHUNK_SIZE/MUA_BIN_SIZE_MODE_3] ARM_ALIGN; // [10 raw data points per raster bin: ~0.8ms -> 3 bins per 30 points]

/******************************************************************************************* */
// Function prototypes
/**
 * Calculate Butterworth filter coefficients Low pass for LFP (2nd order, 250Hz)
 * @param config: Filter configuration structure 
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_butterworth_coeffs_LFP(FilterConfig *config);

/**
 * Calculate Butterworth filter coefficients Low pass for ESA (1st order, 12Hz)
 * @param config: Filter configuration structure 
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_butterworth_coeffs_ESA(FilterConfig *config);

/**
 * Calculate high-pass Butterworth filter coefficients for ESA (1st order, 250Hz)
 * @param config: Filter configuration structure
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status calculate_highpass_butterworth_coeffs_ESA(FilterConfig *config);

/**
 * Initialize low-pass filter for LFP (2nd order, 250Hz)
 * @param order: Filter order (must be even)
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_lowpass_filter_LFP(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate);

/**
 * Initialize low-pass filter for ESA (1st order, 12Hz)
 * @param order: Filter order
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_lowpass_filter_ESA(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate);

/**
 * Initialize high-pass filter for ESA (1st order, 250Hz)
 * @param order: Filter order
 * @param cutoff_freq: Cutoff frequency in Hz
 * @param sampling_rate: Sampling rate in Hz
 * @return: ARM_MATH_SUCCESS on success
 */
arm_status init_highpass_filter_ESA(uint8_t order, float32_t cutoff_freq, float32_t sampling_rate);

/**
 * Set spike detection threshold for a specific channel
 * @param channel: Channel index
 * @param threshold: Spike detection threshold
 */
void set_spike_threshold(uint8_t channel, float32_t threshold);

/**
 * Decimate signal by integer factor using ARM CMSIS DSP
 * @param input: Input signal
 * @param output: Output decimated signal
 * @param input_length: Input signal length
 * @param factor: Decimation factor
 * @return: Output signal length
 */
static inline uint32_t decimate_signal_arm(const float32_t *input, float32_t *output, uint32_t input_length, uint32_t factor);

/**
 * ARM CMSIS DSP optimized spike detection with MUA extraction
 * @param signal: High-pass filtered signal
 * @param mua_data: Output MUA data
 * @param length: Signal length
 * @param channel: Channel index
 * @return: Number of detected spikes
 */
static inline void detect_spikes_and_extract_mua(const float32_t *signal, uint16_t *mua_data, uint32_t length, uint8_t channel);

/**
 * Main neural signal processing function for 12.5kHz input
 * Generates three outputs:
 * 1. LFP: 2nd order IIR lowpass (250Hz) + 10x decimation -> 1.25kHz
 * 2. ESA: 1st order IIR highpass (250Hz) -> rectify -> 1st order IIR lowpass (12Hz) + 10x decimation -> 1.25kHz  
 * 3. MUA: 1st order IIR highpass (250Hz) -> spike detection -> MUA bins
 * @param input_data: Input neural data [channels x samples] at 12.5kHz
 * @param samples_per_channel: Number of samples per channel
 * @param lfp_output: Output LFP data (decimated to 1.25kHz)
 * @param esa_output: Output ESA data (decimated to 1.25kHz)
 * @param mua_data: Output MUA data (spike events in bins)
 * @return: Number of output samples after decimation
 */
uint32_t process_neural_signals_mode3(const float32_t *input_data, uint32_t samples_per_channel,
                                     float32_t *lfp_output, uint16_t *mua_data, float32_t *esa_output);

// ADC converter int16 -> float
void convert_rhd2132_samples(u16_t* adc_data, float_t* float_data, uint32_t num_samples, float32_t filter_scale, bool inttofloat);

// saturation protection: 检查 filter state： 出现溢出就清零
void saturation_protection(float32_t data ,int channel, int lowpass);

#endif
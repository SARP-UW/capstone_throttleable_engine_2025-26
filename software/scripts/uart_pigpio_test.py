import pigpio
import time
import RPI.GPIO as GPIO

# Initialize pigpio
pi = pigpio.pi()
if not pi.connected:
    print("Failed to connect to pigpio daemon. Make sure pigpiod is running.")
    exit()

TX_PIN = 14       # The GPIO pin you use for UART TX
TX_ENABLE = 18    # The GPIO pin connected to the 74AHCT125 *1OE
BAUD = 115200     # Hiwonder servo baud rate

# Ensure pins are set as outputs
# pi.set_mode(TX_PIN, pigpio.OUTPUT)
# pi.set_mode(TX_ENABLE, pigpio.OUTPUT)

GPIO.setmode(GPIO.BCM)
GPIO.setup(TX_ENABLE, GPIO.OUT, initial=GPIO.HIGH)



# Start with TX_ENABLE HIGH (Buffer disabled / listening mode)
print("High")
# pi.write(TX_ENABLE, 1) 
GPIO.output(TX_ENABLE, GPIO.HIGH)

##### DEBUGGING
time.sleep(2)
print("Low")
# pi.write(TX_ENABLE, 0)  # Idle state for UART is HIGH
GPIO.output(TX_ENABLE, GPIO.LOW)

time.sleep(2)
print("High")
# pi.write(TX_ENABLE, 1)  # Set TX pin high
GPIO.output(TX_ENABLE, GPIO.HIGH)
#####git 

# def send_servo_command(data_bytes):
#     # 1. Calculate transmission timing
#     # 1 Start bit + 8 Data bits + 1 Stop bit = 10 bits per byte
#     bits_total = len(data_bytes) * 10
    
#     # Calculate exact duration in microseconds
#     duration_us = int((bits_total * 1_000_000) / BAUD)
    
#     # Add a 20 microsecond margin to prevent clipping the stop bit
#     margin_us = 20 
#     total_wave_time = margin_us + duration_us + margin_us

#     # 2. Build the Waveform
#     pi.wave_clear()
    
#     # Add the serial data. We offset it by 'margin_us' so the buffer 
#     # has time to turn on before the first start bit flies out.
#     pi.wave_add_serial(TX_PIN, BAUD, data_bytes, offset=margin_us)
    
#     # Add the TX_ENABLE GPIO toggles to the SAME wave
#     # pigpio.pulse(gpio_on_mask, gpio_off_mask, delay_to_next_pulse_us)
#     enable_pulses = [
#         # At t=0: Turn TX_ENABLE LOW (buffer ON). Wait for total transmission time.
#         pigpio.pulse(0, 1 << TX_ENABLE, total_wave_time),
        
#         # At t=total_wave_time: Turn TX_ENABLE HIGH (buffer OFF). Wait 0.
#         pigpio.pulse(1 << TX_ENABLE, 0, 0)
#     ]
#     pi.wave_add_generic(enable_pulses)
    
#     # 3. Compile and Send via DMA
#     wave_id = pi.wave_create()
#     pi.wave_send_once(wave_id)
    
#     # 4. Wait for DMA to finish executing
#     # this is not necessary but we need to make sure the wave is done before we delete it from memory
#     # make sure its done before reading on RX
#     while pi.wave_tx_busy():
#         time.sleep(0.001)
        
#     # Clean up the memory
#     pi.wave_delete(wave_id)

# # Example Usage:
# command_data = b'\x55\x55\x08\x03\x01\x00'
# send_servo_command(command_data)

# # You can now immediately read from standard serial RX!
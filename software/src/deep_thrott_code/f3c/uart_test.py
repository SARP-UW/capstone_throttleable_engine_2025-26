import serial
import time
import RPi.GPIO as GPIO

TX_ENABLE_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(TX_ENABLE_PIN, GPIO.OUT, initial=GPIO.HIGH)

ser = serial.Serial("/dev/ttyS0", baudrate=115200, timeout=1.0)
ser.reset_input_buffer()
ser.reset_output_buffer()

# Build ID request packet manually
# 0x55, 0x55, 0xFE, 0x03, 0x0E, checksum
# checksum = ~(0xFE + 0x03 + 0x0E) & 0xFF = ~(0x0F) & 0xFF = 0xF0... wait
packet = bytes([0x55, 0x55, 0xFE, 0x03, 0x0E, 0xF0])
print(f"Sending: {list(packet)}")

GPIO.output(TX_ENABLE_PIN, GPIO.LOW)
ser.write(packet)
ser.flush()
GPIO.output(TX_ENABLE_PIN, GPIO.HIGH)

ser.read(len(packet))
time.sleep(0.2)
print(f"Bytes waiting: {ser.in_waiting}")
if ser.in_waiting:
    raw = ser.read(ser.in_waiting)
    print(f"Raw response: {list(raw)}")
else:
    print("Nothing received")

ser.close()
GPIO.cleanup()
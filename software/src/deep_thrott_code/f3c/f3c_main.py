import RPi.GPIO as GPIO
import time

# single valve actuation test

pin = 21

print("Raising pin high")
GPIO.output(pin, GPIO.HIGH)

time.sleep(10)

print("Raising pin low")
GPIO.output(pin, GPIO.LOW)

GPIO. cleanup()
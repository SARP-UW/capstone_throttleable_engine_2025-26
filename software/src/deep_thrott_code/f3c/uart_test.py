import time
import pigpio

TX_ENABLE_PIN = 20
pi = pigpio.pi()

# TX_ENABLE pin setup
pi.set_mode(TX_ENABLE_PIN, pigpio.OUTPUT)

try:
    while True:
        print(f"Pulling ts shit high")
        pi.write(TX_ENABLE_PIN, 1) # pull ts shit high
        time.sleep(1)
        print(f"Pulling ts shit low")
        pi.write(TX_ENABLE_PIN, 0) # pull ts shit low
except KeyboardInterrupt:
    pi.stop()
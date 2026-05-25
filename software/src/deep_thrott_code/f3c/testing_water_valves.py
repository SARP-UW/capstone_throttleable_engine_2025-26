from valve import WaterValvePWM
import time

print("TESTING")
PWM_PIN = 12
print("Testing WaterValvePWM class")
print(f"Using pin: {PWM_PIN}")
water_valve = WaterValvePWM("water_valve", PWM_PIN)
time.sleep(1)

while True:
    water_valve.open()
    time.sleep(5)
    water_valve.close()
    time.sleep(5)
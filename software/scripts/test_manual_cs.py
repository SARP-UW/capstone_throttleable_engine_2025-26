import time
import spidev
import RPi.GPIO as GPIO

# =========================
# USER SETTINGS
# =========================

SPI_BUS = 0
SPI_DEVICE = 0          # Use /dev/spidev0.0, but hardware CS is disabled
SPI_SPEED_HZ = 500_000
SPI_MODE = 1            # ADS124S0x usually uses SPI mode 1

ADC_CS_PINS = {
    "ADC1": 8,           # BCM GPIO8
    "ADC2": 7,           # BCM GPIO7
    "ADC3": 16,          # change this to your ADC3 CS GPIO
}

# ADS124S0x commands/registers
CMD_RESET = 0x06
CMD_START = 0x08
CMD_STOP  = 0x0A
CMD_RDATA = 0x12
CMD_RREG  = 0x20
CMD_WREG  = 0x40

N_REGS_TO_READ = 18     # read first 18 registers for sanity check

# =========================
# GPIO / SPI SETUP
# =========================

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for name, pin in ADC_CS_PINS.items():
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)

spi = spidev.SpiDev()
spi.open(SPI_BUS, SPI_DEVICE)
spi.max_speed_hz = SPI_SPEED_HZ
spi.mode = SPI_MODE
spi.no_cs = True        # IMPORTANT: disables Linux hardware CS


def deselect_all():
    for pin in ADC_CS_PINS.values():
        GPIO.output(pin, GPIO.HIGH)


def xfer_adc(adc_name, tx, delay_s=5e-6):
    """
    Manual chip-select SPI transaction.
    Only selected ADC CS goes low.
    """
    cs = ADC_CS_PINS[adc_name]

    deselect_all()
    time.sleep(delay_s)

    GPIO.output(cs, GPIO.LOW)
    time.sleep(delay_s)

    rx = spi.xfer2(tx)

    time.sleep(delay_s)
    GPIO.output(cs, GPIO.HIGH)
    time.sleep(delay_s)

    return rx


def send_cmd(adc_name, cmd):
    return xfer_adc(adc_name, [cmd])


def read_regs(adc_name, start_reg=0x00, nregs=N_REGS_TO_READ):
    """
    ADS124S0x RREG format:
    001r rrrr, nnnn nnnn
    where second byte = number of registers - 1
    """
    tx = [CMD_RREG | (start_reg & 0x1F), nregs - 1] + [0x00] * nregs
    rx = xfer_adc(adc_name, tx)
    return rx[2:]


def reset_adc(adc_name):
    print(f"\nResetting {adc_name}")
    send_cmd(adc_name, CMD_RESET)
    time.sleep(0.01)


def test_adc(adc_name):
    print(f"\n========== Testing {adc_name} ==========")

    reset_adc(adc_name)

    regs = read_regs(adc_name)
    print(f"{adc_name} registers:")
    print(" ".join(f"0x{x:02X}" for x in regs))

    all_zero = all(x == 0x00 for x in regs)
    all_ff = all(x == 0xFF for x in regs)

    if all_zero:
        print(f"WARNING: {adc_name} returned all 0x00")
    elif all_ff:
        print(f"WARNING: {adc_name} returned all 0xFF")
    else:
        print(f"{adc_name} register read looks nontrivial")

    return regs


def main():
    print("Manual CS ADS124S0x SPI test")
    print("Make sure hardware CE0/CE1 are NOT connected to ADC CS lines.")
    print("All ADC CS pins should be GPIO-controlled and idle HIGH.\n")

    deselect_all()
    time.sleep(0.1)

    # Test each ADC individually
    results = {}
    for adc_name in ADC_CS_PINS:
        results[adc_name] = test_adc(adc_name)

    # Key test: read ADC1, then initialize/read ADC3, then read ADC1 again
    print("\n========== Cross-interference test ==========")

    print("\nReading ADC1 before ADC3 reset/read:")
    adc1_before = read_regs("ADC1")
    print(" ".join(f"0x{x:02X}" for x in adc1_before))

    print("\nResetting/reading ADC3:")
    reset_adc("ADC3")
    adc3_regs = read_regs("ADC3")
    print(" ".join(f"0x{x:02X}" for x in adc3_regs))

    print("\nReading ADC1 after ADC3 reset/read:")
    adc1_after = read_regs("ADC1")
    print(" ".join(f"0x{x:02X}" for x in adc1_after))

    if adc1_before == adc1_after:
        print("\nPASS: ADC1 registers stayed consistent after talking to ADC3.")
    else:
        print("\nFAIL/WARNING: ADC1 registers changed after talking to ADC3.")
        print("This suggests CS overlap, MISO contention, or an ADC3 transaction affecting the bus.")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    finally:
        deselect_all()
        spi.close()
        GPIO.cleanup()
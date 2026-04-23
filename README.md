# EMG-Flappy-bird-pyQT

The flap of the on-screen character is actuated by electromyography (EMG) signals generated when the user flexes their forearm.

## Hardware Requirements
* **Raspberry Pi 4**
* **3-Lead Surface EMG Sensor** (Connected via a custom Op-Amp processing circuit to a Bluetooth-enabled microcontroller like the Arduino MKR WiFi 1010)
* **Touchscreen Display** (Connected via DSI/HDMI and GPIO for touch)
* **Custom Enclosure** (MDF/Acrylic laser-cut box < 9" x 9" x 6")
* **Power Supply** (15W USB-C for Pi, 5V/9V configurations for circuitry)

## Software Stack
* **Python 3**
* **PyQt5** (UI, Menus, and Game Rendering)
* **PyQtGraph** (Live real-time EMG amplitude graphing)
* **Bleak & qasync** (Asynchronous Bluetooth Low Energy communication)
* **pigpio** (Bare-metal microsecond PWM control for jitter-free servo operation)

## Wiring the SG92R Servo
Ensure the Raspberry Pi is powered off before connecting jumper wires.
* **Signal (Orange/Yellow wire):** GPIO 12 (Physical Pin 32)
* **Power (Red wire):** 5V Power (Physical Pin 2 or 4)
* **Ground (Brown/Black wire):** Ground (Physical Pin 6 or similar)

## Installation & Setup
1. Clone this repository to your Raspberry Pi.
2. Set up the Conda environment using the provided environment file:
   ```bash
   conda env create -f emg_environment.yml
   conda activate emgLAB
   ```
3. Install the required asynchronous and hardware libraries:
   ```bash
   pip install qasync bleak pyqtgraph pigpio
   ```
4. **Update MAC Address:** Open `main.py` and ensure the `ADDRESS` variable at the top matches your specific Bluetooth device's MAC address.

## Running the Game
**CRITICAL:** Because this system uses bare-metal PWM control to prevent motor jitter, you MUST start the hardware daemon before running the Python script.

1. Start the `pigpio` daemon:
   ```bash
   sudo pigpiod
   ```
2. Activate your environment and run the main game script:
   ```bash
   conda activate emgLAB
   python main.py
   ```
3. When finished, cleanly terminate the daemon to free up the GPIO pins:
   ```bash
   sudo killall pigpiod
   ```

## Calibration & Gameplay
Because EMG signals vary wildly based on skin impedance and electrode placement, the system requires per-session calibration before gameplay.
1. **Connect to BLE:** Ensure your EMG processing board is powered on. Click the connect button on the GUI.
2. **Resting Baseline:** Relax your arm completely for 2 seconds to calculate resting noise.
3. **Flexing Threshold:** Flex as hard as you can for 2 seconds. The system sets a custom "Jump Threshold" (Red Dashed Line) and a highly responsive "Refractory Drop Threshold" (Yellow Dashed Line) on the live graph.
4. **Gameplay:** A flex that breaks the Red Threshold causes the bird to jump. You must relax your muscle below the Yellow Threshold before you can jump again (preventing double-entries).
5. **Victory:** Navigate 8 pipes to sweep the physical servo motor progress bar to 180 degrees and win the game!

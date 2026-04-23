import sys
import random
import asyncio
import qasync
import time
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QStackedWidget
from PyQt5.QtCore import QTimer, Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QFont
from bleak import BleakScanner, BleakClient

import pyqtgraph as pg 
import pigpio 

# --- BLE CONFIGURATION ---
#replace with appropriate configuration
ADDRESS = "58:BF:25:3A:FE:F6" 
UART_CHAR_UUID = "5212ddd0-29e5-11eb-adc1-0242ac120002"

class FlappyGameWidget(QWidget):
    def __init__(self, update_score_callback):
        super().__init__()
        self.update_score_callback = update_score_callback
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.game_loop)
        
        self.gravity = 0.5       
        self.jump_strength = -7.5 
        self.pipe_speed = 3      
        self.pipe_width = 70
        self.pipe_gap = 250      
        
        self.state = "READY"
        self.reset_game_vars()

    def reset_game_vars(self):
        self.bird_y = self.height() / 2 if self.height() > 0 else 200.0
        self.bird_vy = 0.0
        self.bird_size = 30
        self.pipes = []
        self.score = 0
        self.update_score_callback(self.score)

    def handle_flex_input(self):
        if self.state in ["READY", "GAMEOVER", "VICTORY"]:
            self.reset_game_vars()
            self.state = "PLAYING"
            self.spawn_pipe(self.width())
            self.timer.start(30)
            self.flap()
        elif self.state == "PLAYING":
            self.flap()

    def flap(self):
        self.bird_vy = self.jump_strength

    def spawn_pipe(self, x_position):
        max_gap_y = max(50, self.height() - self.pipe_gap - 50)
        gap_y = random.randint(50, max_gap_y)
        self.pipes.append({'x': x_position, 'gap_y': gap_y})

    def game_loop(self):
        if self.state != "PLAYING": return

        self.bird_vy += self.gravity
        self.bird_y += self.bird_vy

        for p in self.pipes:
            p['x'] -= self.pipe_speed

        if len(self.pipes) == 0 or self.pipes[-1]['x'] < self.width() - 400:
            self.spawn_pipe(self.width())

        if len(self.pipes) > 0 and self.pipes[0]['x'] < -self.pipe_width:
            self.pipes.pop(0)
            self.score += 1
            self.update_score_callback(self.score) 
            
            if self.score >= 8:
                self.victory()
                return

        bird_rect = QRect(100, int(self.bird_y), self.bird_size, self.bird_size)
        
        if self.bird_y > self.height() or self.bird_y < 0:
            self.game_over()

        for p in self.pipes:
            top_pipe = QRect(p['x'], 0, self.pipe_width, p['gap_y'])
            bottom_pipe_y = p['gap_y'] + self.pipe_gap
            bottom_pipe = QRect(p['x'], bottom_pipe_y, self.pipe_width, self.height() - bottom_pipe_y)
            
            if bird_rect.intersects(top_pipe) or bird_rect.intersects(bottom_pipe):
                self.game_over()

        self.update()

    def game_over(self):
        self.state = "GAMEOVER"
        self.timer.stop()
        self.update()
        
    def victory(self):
        self.state = "VICTORY"
        self.timer.stop()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(135, 206, 235))

        painter.setBrush(QColor(34, 139, 34))
        for p in self.pipes:
            painter.drawRect(p['x'], 0, self.pipe_width, p['gap_y']) 
            bottom_pipe_y = p['gap_y'] + self.pipe_gap
            painter.drawRect(p['x'], bottom_pipe_y, self.pipe_width, self.height() - bottom_pipe_y)

        painter.setBrush(QColor(255, 215, 0))
        painter.drawEllipse(100, int(self.bird_y), self.bird_size, self.bird_size)

        painter.setPen(Qt.black)
        painter.setFont(QFont("Arial", 20, QFont.Bold))
        
        if self.state == "READY":
            painter.drawText(self.rect(), Qt.AlignCenter, "Ready!\nFlex to Start")
        elif self.state == "GAMEOVER":
            painter.setPen(QColor(200, 0, 0)) 
            painter.drawText(self.rect(), Qt.AlignCenter, f"Game Over!\nScore: {self.score}\nFlex to restart.")
        elif self.state == "VICTORY":
            painter.setPen(QColor(0, 100, 0)) 
            painter.drawText(self.rect(), Qt.AlignCenter, f"Congratulations!\nYou passed 8 pipes!\nFlex to play again.")

class EMGGameApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BLE EMG Flappy Bird")
        self.setGeometry(100, 100, 800, 480) 
        
        # --- BARE METAL SERVO SETUP ---
        self.pi = pigpio.pi() 
        if not self.pi.connected: 
            print("Error: Could not connect to pigpiod. The daemon is not running!") 
            sys.exit(1)
            
        self.servo_pin = 12 
        # INVERTED: Initialize at 2400us (0-score starting position)
        self.pi.set_servo_pulsewidth(self.servo_pin, 2400) 
        
        self.client = None
        self.device = None
        
        self.resting_baseline = 0
        self.flex_threshold = 255 
        self.drop_threshold = 0
        
        self.last_flap_time = 0.0
        self.refractory_duration = 0.05 
        
        self.is_calibrating = False
        self.temp_calibration_data = []
        
        self.init_main_layout()

    def init_main_layout(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        
        self.stacked_widget = QStackedWidget()
        self.init_connection_screen()
        self.init_calibration_screen()
        self.init_game_screen()
        main_layout.addWidget(self.stacked_widget, stretch=2) 
        
        self.plot_widget = pg.PlotWidget(title="Live EMG Amplitude")
        self.plot_widget.setYRange(0, 255)
        self.plot_widget.setLabel('left', 'Bit Value (0-255)')
        self.plot_widget.showGrid(x=False, y=True)
        
        self.emg_curve = self.plot_widget.plot(pen=pg.mkPen('c', width=2))
        
        self.thresh_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('r', width=2, style=Qt.DashLine))
        self.drop_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('y', width=2, style=Qt.DashLine))
        
        self.plot_widget.addItem(self.thresh_line)
        self.plot_widget.addItem(self.drop_line)
        
        self.emg_data = [0] * 100 
        
        main_layout.addWidget(self.plot_widget, stretch=1) 
        self.setCentralWidget(central_widget)

    def init_connection_screen(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.status_label = QLabel("Welcome to Flappy Wrist.\nEnsure your BLE Device is powered on.")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.btn_connect = QPushButton("Connect to EMG Bluetooth")
        self.btn_connect.clicked.connect(self.handle_connect)
        layout.addWidget(self.status_label)
        layout.addWidget(self.btn_connect)
        widget.setLayout(layout)
        self.stacked_widget.addWidget(widget)

    def init_calibration_screen(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.cal_label = QLabel("Calibration Setup\nWatch the graph to the right.")
        self.cal_label.setAlignment(Qt.AlignCenter)
        
        self.btn_baseline = QPushButton("1. Relax Arm (Record Baseline)")
        self.btn_baseline.clicked.connect(self.record_baseline)
        
        self.btn_flex = QPushButton("2. Flex Arm (Record Threshold)")
        self.btn_flex.clicked.connect(self.record_flex)
        self.btn_flex.setEnabled(False) 
        
        self.btn_start = QPushButton("3. Enter Game")
        self.btn_start.clicked.connect(self.start_gameplay)
        self.btn_start.setEnabled(False) 
        
        layout.addWidget(self.cal_label)
        layout.addWidget(self.btn_baseline)
        layout.addWidget(self.btn_flex)
        layout.addWidget(self.btn_start)
        widget.setLayout(layout)
        self.stacked_widget.addWidget(widget)

    def init_game_screen(self):
        self.game_container = QWidget()
        self.game_layout = QVBoxLayout()
        self.score_label = QLabel("Pipes Passed: 0 / 8")
        self.score_label.setAlignment(Qt.AlignCenter)
        self.score_label.setFont(QFont("Arial", 16, QFont.Bold))
        self.game_canvas = FlappyGameWidget(self.update_progress_bar)
        self.game_layout.addWidget(self.score_label)
        self.game_layout.addWidget(self.game_canvas, stretch=1) 
        self.game_container.setLayout(self.game_layout)
        self.stacked_widget.addWidget(self.game_container)

    def start_gameplay(self):
        self.stacked_widget.setCurrentIndex(2)
        self.game_canvas.reset_game_vars()
        self.game_canvas.state = "READY"

    @qasync.asyncSlot()
    async def record_baseline(self):
        self.cal_label.setText("Recording Baseline... KEEP ARM RELAXED")
        self.btn_baseline.setEnabled(False)
        self.temp_calibration_data = []
        self.is_calibrating = True
        
        await asyncio.sleep(2.0) 
        
        self.is_calibrating = False
        if self.temp_calibration_data:
            self.resting_baseline = sum(self.temp_calibration_data) / len(self.temp_calibration_data)
        
        self.cal_label.setText(f"Baseline Set: {int(self.resting_baseline)}\nNow, prepare to flex.")
        self.btn_flex.setEnabled(True)

    @qasync.asyncSlot()
    async def record_flex(self):
        self.cal_label.setText("FLEX NOW! Recording in 1 second...")
        self.btn_flex.setEnabled(False)
        await asyncio.sleep(1.0)
        
        self.cal_label.setText("Recording Flex... HOLD IT MAX!")
        self.temp_calibration_data = []
        self.is_calibrating = True
        
        await asyncio.sleep(2.0) 
        
        self.is_calibrating = False
        if self.temp_calibration_data:
            peak_flex = max(self.temp_calibration_data)
            self.flex_threshold = self.resting_baseline + ((peak_flex - self.resting_baseline) * 0.35)
            if self.flex_threshold < self.resting_baseline + 10:
                self.flex_threshold = self.resting_baseline + 10
            
            self.drop_threshold = self.resting_baseline + ((self.flex_threshold - self.resting_baseline) * 0.9)
            
            self.thresh_line.setValue(self.flex_threshold)
            self.drop_line.setValue(self.drop_threshold)
            
        self.cal_label.setText(f"Calibration Complete!\nBaseline: {int(self.resting_baseline)} | Threshold: {int(self.flex_threshold)}")
        self.btn_start.setEnabled(True)

    @qasync.asyncSlot()
    async def handle_connect(self):
        self.status_label.setText(f"Scanning for device {ADDRESS}...")
        self.btn_connect.setEnabled(False)
        self.device = await BleakScanner.find_device_by_address(ADDRESS)
        if not self.device:
            self.status_label.setText("Device not found. Check MAC address and power.")
            self.btn_connect.setEnabled(True)
            return

        self.status_label.setText("Found device. Connecting...")
        if self.client is not None:
            await self.client.stop()
            
        self.client = BleakClient(self.device)
        await self.client.connect()
        self.status_label.setText("Connected! Starting stream...")
        await self.client.start_notify(UART_CHAR_UUID, self.notification_handler)
        self.stacked_widget.setCurrentIndex(1)

    def notification_handler(self, characteristic, data: bytearray):
        convertData = list(data)
        max_val = max(convertData)
        
        self.emg_data.pop(0)
        self.emg_data.append(max_val)
        self.emg_curve.setData(self.emg_data)
        
        if self.is_calibrating:
            self.temp_calibration_data.extend(convertData)
            return

        is_flexing = max_val >= self.flex_threshold
        current_time = time.time()

        if is_flexing and (current_time - self.last_flap_time) >= self.refractory_duration:
            self.last_flap_time = current_time
            if self.stacked_widget.currentIndex() == 2:
                self.game_canvas.handle_flex_input()

    def update_progress_bar(self, score):
        self.score_label.setText(f"Pipes Passed: {score} / 8")
        
        fraction = min(score / 8.0, 1.0) 
        
        pulse_width = int(2400 - (fraction * (2400 - 500))) 
        
        self.pi.set_servo_pulsewidth(self.servo_pin, pulse_width) 

    def closeEvent(self, event):
        if self.client is not None:
            loop = asyncio.get_event_loop()
            loop.create_task(self.client.disconnect())
        
        self.pi.set_servo_pulsewidth(self.servo_pin, 0) 
        self.pi.stop() 
        
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = EMGGameApp()
    window.show()
    with loop:
        loop.run_forever()

if __name__ == '__main__':
    main()
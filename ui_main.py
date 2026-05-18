"""
ui_main.py — Lightweight, branded GUI for the Voice-to-Voice Pipeline.
Includes single-instance locking that brings the existing UI to the front.
"""

import sys
import os
import socket
import logging
import asyncio
from threading import Thread
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QTextEdit, QLabel, QHBoxLayout, QFrame
)
from PyQt6.QtGui import QPixmap, QIcon, QFont, QColor, QPalette, QCloseEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, pyqtSlot

# Import our pipeline core
from config import load_config
from audio_router import managed_input_router, managed_output_router
from pipeline import VoicePipeline

# Configure standard logging to intercept it for the UI
class UILogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S'))

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)


# --- Pipeline Runner Thread ---
class PipelineRunner(QThread):
    log_signal = pyqtSignal(str)
    stopped_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._is_running = False

    def run(self):
        self._is_running = True
        self.pipeline: Optional[VoicePipeline] = None
        try:
            asyncio.run(self._async_run())
        except Exception as e:
            self.log_signal.emit(f"[ERROR] Pipeline crashed: {e}")
        finally:
            self._is_running = False
            self.stopped_signal.emit()

    async def _async_run(self):
        self.loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()

        try:
            cfg = load_config()
            self.log_signal.emit("Config loaded successfully.")
            
            with managed_output_router(cfg.audio) as out_router:
                pipeline = VoicePipeline(cfg, out_router)
                self.pipeline = pipeline  # expose for UI intercept calls
                with managed_input_router(cfg.audio, pipeline.audio_queue, self.loop) as _in_router:
                    await pipeline.start()
                    self.log_signal.emit("Pipeline live! Listening for audio...")
                    
                    # Wait until shutdown requested
                    await self._shutdown_event.wait()
                    self.log_signal.emit("Stopping pipeline...")
                    await pipeline.stop()
        except Exception as e:
            self.log_signal.emit(f"[FATAL] {e}")
        finally:
            self.pipeline = None

    def stop(self):
        if self.loop and self._shutdown_event and self._is_running:
            self.loop.call_soon_threadsafe(self._shutdown_event.set)


# --- Single Instance IPC Server ---
class SingleInstanceServer(QThread):
    show_window_signal = pyqtSignal()
    PORT = 45544

    def __init__(self):
        super().__init__()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def bind(self) -> bool:
        try:
            self.server.bind(("127.0.0.1", self.PORT))
            self.server.listen(1)
            return True
        except OSError:
            # Port in use -> Another instance is running
            return False

    def run(self):
        while True:
            try:
                conn, _ = self.server.accept()
                data = conn.recv(1024).decode("utf-8")
                if data == "SHOW":
                    self.show_window_signal.emit()
                conn.close()
            except Exception:
                break


# --- Main UI Window ---
class CallAgentUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Call Agent - Real-time Voice AI")
        self.setFixedSize(450, 600)
        
        # UI Styling (Dark Mode)
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QLabel { color: #ffffff; }
            QTextEdit { 
                background-color: #1e1e1e; 
                color: #00ff00; 
                border: 1px solid #333333; 
                border-radius: 8px;
                padding: 5px;
                font-family: monospace;
            }
            QPushButton { 
                background-color: #2b2b2b; 
                color: #ffffff; 
                border: 2px solid #3a3a3a; 
                border-radius: 10px; 
                padding: 10px; 
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #1a1a1a; }
            QPushButton#startBtn { background-color: #1e4620; border-color: #2e602e; }
            QPushButton#startBtn:hover { background-color: #2e602e; }
            QPushButton#stopBtn { background-color: #601e1e; border-color: #802e2e; }
            QPushButton#stopBtn:hover { background-color: #802e2e; }
            QPushButton#interceptBtn {
                background-color: #5a2d00;
                border-color: #ff6600;
                color: #ff6600;
                font-size: 12pt;
            }
            QPushButton#interceptBtn:hover { background-color: #7a3d00; }
            QPushButton#resumeBtn {
                background-color: #1a2a5a;
                border-color: #4488ff;
                color: #4488ff;
                font-size: 12pt;
            }
            QPushButton#resumeBtn:hover { background-color: #2a3a7a; }
        """)

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Company Logo
        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = "/home/salman/Documents/projects/website/logos/logo1.png"
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            # Scale logo to reasonable size, keeping aspect ratio
            self.logo_label.setPixmap(pixmap.scaled(300, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo_label.setText("ABT Plus LLC")
            self.logo_label.setStyleSheet("font-size: 24pt; font-weight: bold; color: #ffffff;")
        layout.addWidget(self.logo_label)

        # Title / Status
        self.status_label = QLabel("Ready to Start")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14pt; color: #aaaaaa;")
        layout.addWidget(self.status_label)

        # Controls
        controls_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶  Start Call Agent")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self.start_pipeline)
        
        self.stop_btn = QPushButton("■  Stop Agent")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.clicked.connect(self.stop_pipeline)
        self.stop_btn.setEnabled(False)
        self.stop_btn.hide()

        controls_layout.addWidget(self.start_btn)
        controls_layout.addWidget(self.stop_btn)
        layout.addLayout(controls_layout)

        # Founder intercept row (only visible when pipeline is running)
        intercept_layout = QHBoxLayout()
        self.intercept_btn = QPushButton("⚡  FOUNDER INTERCEPT")
        self.intercept_btn.setObjectName("interceptBtn")
        self.intercept_btn.setToolTip("Instantly silence the AI and take over the call")
        self.intercept_btn.clicked.connect(self.intercept_pipeline)
        self.intercept_btn.hide()

        self.resume_btn = QPushButton("↩  Resume AI")
        self.resume_btn.setObjectName("resumeBtn")
        self.resume_btn.setToolTip("Re-enable AI audio output")
        self.resume_btn.clicked.connect(self.resume_pipeline)
        self.resume_btn.hide()

        intercept_layout.addWidget(self.intercept_btn)
        intercept_layout.addWidget(self.resume_btn)
        layout.addLayout(intercept_layout)

        # Logs area
        log_label = QLabel("Terminal Output:")
        log_label.setStyleSheet("color: #888888; font-size: 10pt;")
        layout.addWidget(log_label)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        # Init Pipeline runner
        self.runner = PipelineRunner()
        self.runner.log_signal.connect(self.append_log)
        self.runner.stopped_signal.connect(self.on_pipeline_stopped)

        # Intercept python logging
        self.log_handler = UILogHandler(self.runner.log_signal)
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.INFO)

        self.append_log("System initialized. Waiting for user input.")

    @pyqtSlot(str)
    def append_log(self, text):
        self.log_area.append(text)
        # Auto-scroll
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_pipeline(self):
        self.status_label.setText("Agent is Running...")
        self.status_label.setStyleSheet("font-size: 14pt; color: #00ff00;")
        self.start_btn.hide()
        self.stop_btn.show()
        self.stop_btn.setEnabled(True)
        self.intercept_btn.show()
        self.resume_btn.hide()
        self.log_area.clear()
        
        self.runner.start()

    def stop_pipeline(self):
        self.status_label.setText("Stopping...")
        self.status_label.setStyleSheet("font-size: 14pt; color: #ffaa00;")
        self.stop_btn.setEnabled(False)
        self.intercept_btn.hide()
        self.resume_btn.hide()
        self.runner.stop()

    @pyqtSlot()
    def intercept_pipeline(self):
        """Founder takeover: instantly silence AI, purge queues."""
        pipeline = getattr(self.runner, 'pipeline', None)
        if pipeline is not None:
            pipeline.hot_interrupt_pipeline()
            self.status_label.setText("FOUNDER ACTIVE — AI Silenced")
            self.status_label.setStyleSheet("font-size: 14pt; color: #ff6600;")
            self.intercept_btn.setEnabled(False)
            self.resume_btn.show()
            self.append_log("[INTERCEPT] Founder has taken over. AI silenced and queues purged.")
        else:
            self.append_log("[WARNING] Pipeline not ready yet.")

    @pyqtSlot()
    def resume_pipeline(self):
        """Re-enable AI audio after a founder intercept."""
        pipeline = getattr(self.runner, 'pipeline', None)
        if pipeline is not None:
            pipeline.reset_interrupt()
            self.status_label.setText("Agent is Running...")
            self.status_label.setStyleSheet("font-size: 14pt; color: #00ff00;")
            self.intercept_btn.setEnabled(True)
            self.resume_btn.hide()
            self.append_log("[RESUME] AI audio re-enabled.")

    @pyqtSlot()
    def on_pipeline_stopped(self):
        self.status_label.setText("Ready to Start")
        self.status_label.setStyleSheet("font-size: 14pt; color: #aaaaaa;")
        self.stop_btn.hide()
        self.start_btn.show()
        self.start_btn.setEnabled(True)
        self.append_log("Pipeline stopped entirely.")

    def bring_to_front(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent):
        # Stop runner gracefully on exit
        if self.runner.isRunning():
            self.runner.stop()
            self.runner.wait(5000)
        event.accept()


# --- Single Instance Check ---
def check_single_instance_or_notify():
    # Attempt to bind socket.
    server = SingleInstanceServer()
    if not server.bind():
        # Another instance is running, notify it.
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(("127.0.0.1", SingleInstanceServer.PORT))
            client.sendall(b"SHOW")
            client.close()
        except Exception:
            pass
        sys.exit(0)
    return server

def main():
    # Check if instance exists before initializing UI
    server = check_single_instance_or_notify()
    
    app = QApplication(sys.argv)
    window = CallAgentUI()
    
    # Listen for signals from other attempts
    server.show_window_signal.connect(window.bring_to_front)
    server.start()

    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

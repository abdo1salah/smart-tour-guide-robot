import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

import rclpy
import rclpy.executors
from std_msgs.msg import String

class Ros2SubscriberThread(QThread):
    caption_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.node = None

    def run(self):
        rclpy.init()
        self.node = rclpy.create_node('caption_ui_subscriber')
        self.sub = self.node.create_subscription(
            String,
            '/horus_captions',
            self.listener_callback,
            10
        )
        try:
            rclpy.spin(self.node)
        except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
            pass

    def listener_callback(self, msg):
        print(msg.data)
        self.caption_signal.emit(msg.data)

    def stop(self):
        if self.node:
            self.node.destroy_node()
            rclpy.shutdown()
        self.quit()
        self.wait()



class HorusCaptionUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Horus-Bot Live Captions")
        self.showFullScreen()

        self.setStyleSheet("""
            QWidget {
                background-color: #F5EFE3;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(30, 25, 30, 50)

        self.logo = QLabel("HORUS-BOT")
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setStyleSheet("color: #2B2723; letter-spacing: 3px;")
        self.logo.setFont(QFont("Times New Roman", 28))

        self.subtitle = QLabel("LIVE NARRATION")
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setStyleSheet("color: #C9A24A; letter-spacing: 5px;")
        self.subtitle.setFont(QFont("Arial", 13))

        self.caption = QLabel("Welcome to the Grand Egyptian Museum.")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setMinimumHeight(170)
        self.caption.setStyleSheet("""
            color: #2B2723;
            padding-left: 100px;
            padding-right: 100px;
        """)
        self.caption.setFont(QFont("Arial", 48))

        self.status = QLabel("● Speaking   |   EN")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #9C7A2B; font-weight: bold;")
        self.status.setFont(QFont("Arial", 18))

        layout.addWidget(self.logo)
        layout.addWidget(self.subtitle)
        layout.addStretch()
        layout.addWidget(self.caption)
        layout.addStretch()
        layout.addWidget(self.status)

        self.setLayout(layout)

        self.current_text = ""
        self.needs_clear = False
        self.caption.setText("Ready to guide you...")

        # Start ROS 2 Thread
        self.ros_thread = Ros2SubscriberThread()
        self.ros_thread.caption_signal.connect(self.handle_caption_msg)
        self.ros_thread.start()

    def handle_caption_msg(self, msg_data):
        if msg_data.startswith("APPEND:"):
            if self.needs_clear:
                self.current_text = ""
                self.needs_clear = False
                
            text_chunk = msg_data[len("APPEND:"):]
            self.current_text += text_chunk
            
            # Optional: keep text from getting too long and overflowing
            if len(self.current_text) > 400:
                # Keep the last 400 chars roughly, splitting by space
                self.current_text = "..." + self.current_text[-400:].split(" ", 1)[-1]
                
            self.caption.setText(self.current_text)
            
        elif msg_data.startswith("CLEAR:"):
            self.needs_clear = True

    def closeEvent(self, event):
        self.ros_thread.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = HorusCaptionUI()
    window.show()
    sys.exit(app.exec_())
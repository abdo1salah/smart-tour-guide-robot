#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Range
import serial
import math
import time

class UltrasonicBridge(Node):
    def __init__(self):
        super().__init__('ultrasonic_bridge')
        # Publishers
        self.pub_left = self.create_publisher(Range, '/us_left/range', 10)
        self.pub_center = self.create_publisher(Range, '/us_center/range', 10)
        self.pub_right = self.create_publisher(Range, '/us_right/range', 10)
        
        self.serial_port = None
        self.port_name = '/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.2.2:1.0-port0'
        
        # Diagnostic counters
        self.msg_count = 0
        self.last_report_time = time.monotonic()
        self.last_data_time = None
        
        # Timer to poll serial or attempt connection
        self.timer = self.create_timer(0.05, self.timer_callback)
        # Diagnostic timer — reports every 5 seconds
        self.diag_timer = self.create_timer(5.0, self.report_diagnostics)

    def report_diagnostics(self):
        elapsed = time.monotonic() - self.last_report_time
        if self.serial_port is None:
            self.get_logger().warn('Serial port not connected — retrying...')
        elif self.msg_count == 0:
            if self.last_data_time is None:
                self.get_logger().warn(
                    f'No serial data received since startup '
                    f'(port open, in_waiting={self.serial_port.in_waiting}). '
                    f'Check ESP32 is powered and sending CSV data.')
            else:
                gap = time.monotonic() - self.last_data_time
                self.get_logger().warn(
                    f'No serial data in last {gap:.1f}s '
                    f'(in_waiting={self.serial_port.in_waiting})')
        else:
            self.get_logger().info(
                f'Published {self.msg_count} range triplets in last {elapsed:.1f}s')
        self.msg_count = 0
        self.last_report_time = time.monotonic()

    def timer_callback(self):
        if self.serial_port is None:
            self.connect_serial()
        else:
            self.read_serial()

    def connect_serial(self):
        try:
            self.serial_port = serial.Serial(self.port_name, 115200, timeout=1.0)
            self.get_logger().info(f"Successfully connected to ultrasonic sensor on {self.port_name}")
        except serial.SerialException as e:
            self.get_logger().warn(f"Failed to connect to {self.port_name}: {e}. Retrying...", throttle_duration_sec=2.0)
            self.serial_port = None

    def create_range_msg(self, distance, frame_id):
        msg = Range()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = frame_id
        msg.radiation_type = Range.ULTRASOUND
        msg.field_of_view = 0.52 # ~30 degrees in radians (typical for HC-SR04)
        msg.min_range = 0.02     # 2 cm
        msg.max_range = 2.00     # 200 cm
        msg.range = distance
        return msg

    def read_serial(self):
        try:
            if self.serial_port.in_waiting > 0:
                line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    return
                # Expecting: "left,center,right"
                distances = [float(x) for x in line.split(',')]
                if len(distances) == 3:
                    self.pub_left.publish(self.create_range_msg(distances[0], 'us_left_link'))
                    self.pub_center.publish(self.create_range_msg(distances[1], 'us_center_link'))
                    self.pub_right.publish(self.create_range_msg(distances[2], 'us_right_link'))
                    self.msg_count += 1
                    self.last_data_time = time.monotonic()
                else:
                    self.get_logger().warn(f"Expected 3 values, got {len(distances)}: {line}")
        except ValueError:
            self.get_logger().warn(f"Malformed serial data: {line}")
        except serial.SerialException as e:
            self.get_logger().error(f"Serial port disconnected or error: {e}")
            self.serial_port.close()
            self.serial_port = None
        except OSError as e:
            self.get_logger().error(f"OS Error on serial port: {e}")
            self.serial_port = None

def main(args=None):
    rclpy.init(args=args)
    node = UltrasonicBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.serial_port is not None:
            node.serial_port.close()
            print('Serial port closed.')
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()
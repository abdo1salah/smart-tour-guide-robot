#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Range
import serial
import math

class UltrasonicBridge(Node):
    def __init__(self):
        super().__init__('ultrasonic_bridge')
        
        # Open Serial Port (Update to match your ESP's port, e.g., /dev/ttyUSB0 or /dev/ttyACM0)
        self.serial_port = serial.Serial('/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0', 115200, timeout=1.0)
        
        # Publishers
        self.pub_left = self.create_publisher(Range, '/us_left/range', 10)
        self.pub_center = self.create_publisher(Range, '/us_center/range', 10)
        self.pub_right = self.create_publisher(Range, '/us_right/range', 10)
        
        # Timer to poll serial
        self.timer = self.create_timer(0.05, self.read_serial)

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
        if self.serial_port.in_waiting > 0:
            line = self.serial_port.readline().decode('utf-8').strip()
            try:
                # Expecting: "left,center,right"
                distances = [float(x) for x in line.split(',')]
                if len(distances) == 3:
                    self.pub_left.publish(self.create_range_msg(distances[0], 'us_left'))
                    self.pub_center.publish(self.create_range_msg(distances[1], 'us_center'))
                    self.pub_right.publish(self.create_range_msg(distances[2], 'us_right'))
            except ValueError:
                self.get_logger().warn(f"Malformed serial data: {line}")

def main(args=None):
    rclpy.init(args=args)
    node = UltrasonicBridge()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
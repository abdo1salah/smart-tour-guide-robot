#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan, Range
import math

class ScanToRangeNode(Node):
    def __init__(self):
        super().__init__('scan_to_range_node')
        
        # You can parameterize these or run three instances of this node
        # mapping the topics appropriately in your launch file.
        self.scan_sub = self.create_subscription(
            LaserScan,
            '/us_center/scan', # Input from Gazebo Bridge
            self.scan_callback,
            10)
            
        self.range_pub = self.create_publisher(
            Range, 
            '/us_center/range', # Output to your robot code
            10)

    def scan_callback(self, scan_msg):
        range_msg = Range()
        range_msg.header = scan_msg.header
        
        # Define the sensor type as Ultrasound
        range_msg.radiation_type = Range.ULTRASOUND
        
        # Match these to your physical sensor's specs (e.g., HC-SR04)
        range_msg.field_of_view = 0.52 # ~30 degrees in radians
        range_msg.min_range = 0.02     # 2 cm
        range_msg.max_range = 4.0      # 4 meters
        
        # Find the closest obstacle in the simulated lidar cone
        valid_ranges = [r for r in scan_msg.ranges if not math.isinf(r) and not math.isnan(r)]
        
        if valid_ranges:
            range_msg.range = min(valid_ranges)
        else:
            # If no obstacle is seen, output max range
            range_msg.range = range_msg.max_range 
            
        self.range_pub.publish(range_msg)

def main(args=None):
    rclpy.init(args=args)
    node = ScanToRangeNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
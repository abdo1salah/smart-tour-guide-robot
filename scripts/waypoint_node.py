#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from std_msgs.msg import String
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
import yaml
import os

class WaypointFollower(Node):
    def __init__(self):
        super().__init__('waypoint_follower')
        
        # Declare parameters for the node
        self.declare_parameter('waypoints_file', '/home/abdelrahman/project/src/articubot_one/config/waypoints.yaml')
        self.declare_parameter('trigger_topic', '/tour_commands')
        
        waypoints_file = self.get_parameter('waypoints_file').value
        trigger_topic = self.get_parameter('trigger_topic').value
        
        self.get_logger().info(f"Loading waypoints from: {waypoints_file}")
        self.waypoints = self.load_waypoints(waypoints_file)
        self.current_waypoint_index = 0
        self.waiting_for_trigger = False
        
        if not self.waypoints:
            self.get_logger().error("No waypoints loaded. Shutting down...")
            return
            
        # Action client for Nav2
        self.action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        
        # Publisher for arrived exhibit name
        self.arrival_pub = self.create_publisher(String, '/arrived_exhibit', 10)
        
        # Subscription for the trigger topic
        self.trigger_sub = self.create_subscription(
            String,
            trigger_topic,
            self.trigger_callback,
            10
        )
        
        # Wait for Nav2 action server
        self.get_logger().info('Waiting for navigate_to_pose action server...')
        self.action_client.wait_for_server()
        self.get_logger().info('Action server available!')
        
        # Start the sequence
        self.send_next_waypoint()
        
    def load_waypoints(self, file_path):
        """Loads waypoints from the yaml file."""
        if not os.path.exists(file_path):
            self.get_logger().error(f"File not found: {file_path}")
            return []
            
        try:
            with open(file_path, 'r') as file:
                yaml_data = yaml.safe_load(file)
            return yaml_data.get('waypoints', [])
        except Exception as e:
            self.get_logger().error(f"Failed to load waypoints: {e}")
            return []

    def send_next_waypoint(self):
        """Sends the next waypoint goal to Nav2."""
        if self.current_waypoint_index >= len(self.waypoints):
            self.get_logger().info('All waypoints visited! Mission complete.')
            return
            
        wp = self.waypoints[self.current_waypoint_index]
        name = wp.get('name', f'Waypoint_{self.current_waypoint_index}')
        self.get_logger().info(f"Sending goal for waypoint: '{name}'")
        
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        
        # Extract pose parameters with fallback defaults
        pose_data = wp.get('pose', {})
        pos = pose_data.get('position', {})
        ori = pose_data.get('orientation', {})
        
        goal_msg.pose.pose.position.x = float(pos.get('x', 0.0))
        goal_msg.pose.pose.position.y = float(pos.get('y', 0.0))
        goal_msg.pose.pose.position.z = float(pos.get('z', 0.0))
        
        goal_msg.pose.pose.orientation.x = float(ori.get('x', 0.0))
        goal_msg.pose.pose.orientation.y = float(ori.get('y', 0.0))
        goal_msg.pose.pose.orientation.z = float(ori.get('z', 0.0))
        goal_msg.pose.pose.orientation.w = float(ori.get('w', 1.0))
        
        send_goal_future = self.action_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        """Callback for goal acceptance/rejection."""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Nav2 rejected the goal!')
            return

        self.get_logger().info('Nav2 accepted the goal, navigating...')
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        """Callback for goal completion."""
        status = future.result().status
        
        if status == GoalStatus.STATUS_SUCCEEDED:
            wp_name = self.waypoints[self.current_waypoint_index].get('name', '')
            self.get_logger().info(f"Successfully reached waypoint '{wp_name}'!")
            
            # Publish arrived exhibit message
            arrival_msg = String()
            arrival_msg.data = wp_name
            self.arrival_pub.publish(arrival_msg)
            
            # If not the last waypoint, wait for the trigger
            if self.current_waypoint_index + 1 < len(self.waypoints):
                self.get_logger().info("Waiting for trigger message to proceed to the next waypoint...")
                self.waiting_for_trigger = True
            else:
                # Triggers the mission completion block
                self.current_waypoint_index += 1
                self.send_next_waypoint() 
        else:
            self.get_logger().error(f'Navigation failed with status code: {status}')

    def trigger_callback(self, msg):
        """Callback for trigger topic."""
        if self.waiting_for_trigger:
            self.get_logger().info(f"Received trigger string: '{msg.data}'. Proceeding...")
            self.waiting_for_trigger = False
            self.current_waypoint_index += 1
            self.send_next_waypoint()

def main(args=None):
    rclpy.init(args=args)
    node = WaypointFollower()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()

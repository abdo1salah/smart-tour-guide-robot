#!/usr/bin/env python3

import json
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
        self._current_goal_handle = None
        self._nav_state = 'idle'  # idle | navigating | waiting | mission_complete
        self._tour_active = False
        
        if not self.waypoints:
            self.get_logger().error("No waypoints loaded. Shutting down...")
            return
            
        # Action client for Nav2
        self.action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        
        # Publisher for arrived exhibit name (direct link to live_horus)
        self.arrival_pub = self.create_publisher(String, '/arrived_exhibit', 10)
        
        # Publisher for robot navigation status (consumed by cloud bridge)
        self.status_pub = self.create_publisher(String, '/robot_status', 10)
        
        # Subscription for the trigger topic (direct link from live_horus)
        self.trigger_sub = self.create_subscription(
            String,
            trigger_topic,
            self.trigger_callback,
            10
        )
        
        # Subscription for cloud commands (from horus_cloud_bridge)
        self.cloud_cmd_sub = self.create_subscription(
            String,
            '/cloud_commands',
            self._on_cloud_command,
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

    # ---------------------------------------------------------------
    # Navigation Status Publisher
    # ---------------------------------------------------------------
    def _publish_status(self, state: str):
        """Publish navigation state as JSON to /robot_status."""
        self._nav_state = state
        wp_name = ''
        if 0 <= self.current_waypoint_index < len(self.waypoints):
            wp_name = self.waypoints[self.current_waypoint_index].get('name', '')

        status = {
            'state': state,
            'currentWaypoint': wp_name,
            'waypointIndex': self.current_waypoint_index,
            'totalWaypoints': len(self.waypoints),
        }
        msg = String()
        msg.data = json.dumps(status)
        self.status_pub.publish(msg)
        self.get_logger().debug(f'Published robot_status: {state}')

    # ---------------------------------------------------------------
    # Cloud Command Handler
    # ---------------------------------------------------------------
    def _on_cloud_command(self, msg: String):
        """Handle commands forwarded by the cloud bridge."""
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        cmd_type = cmd.get('type', '')

        if cmd_type == 'start_tour':
            self._handle_start_tour()
        elif cmd_type == 'skip':
            self._handle_skip()
        elif cmd_type == 'end_tour':
            self._handle_end_tour()
        elif cmd_type == 'find_robot':
            self._handle_find_robot()
        # Other command types are handled by live_horus, ignore here

    def _handle_start_tour(self):
        """Reset to the first waypoint and begin navigation."""
        self.get_logger().info('Cloud command: start_tour — resetting to first waypoint')
        self._cancel_current_goal()
        self.current_waypoint_index = 0
        self.waiting_for_trigger = False
        self._tour_active = True
        self.send_next_waypoint()

    def _handle_skip(self):
        """Cancel current goal and navigate to the next waypoint."""
        self.get_logger().info('Cloud command: skip — jumping to next waypoint')
        self._cancel_current_goal()
        self.waiting_for_trigger = False
        self.current_waypoint_index += 1
        self.send_next_waypoint()

    def _handle_end_tour(self):
        """Cancel navigation and stop the tour."""
        self.get_logger().info('Cloud command: end_tour — stopping navigation')
        self._cancel_current_goal()
        self.waiting_for_trigger = False
        self._tour_active = False
        self._publish_status('idle')

    def _handle_find_robot(self):
        """Publish a one-shot status dump."""
        self.get_logger().info('Cloud command: find_robot — publishing current status')
        self._publish_status(self._nav_state)

    def _cancel_current_goal(self):
        """Cancel the active Nav2 goal if one exists."""
        if self._current_goal_handle is not None:
            self.get_logger().info('Cancelling active Nav2 goal...')
            try:
                self._current_goal_handle.cancel_goal_async()
            except Exception as e:
                self.get_logger().warn(f'Goal cancel failed: {e}')
            self._current_goal_handle = None

    # ---------------------------------------------------------------
    # Navigation
    # ---------------------------------------------------------------
    def send_next_waypoint(self):
        """Sends the next waypoint goal to Nav2."""
        if self.current_waypoint_index >= len(self.waypoints):
            self.get_logger().info('All waypoints visited! Mission complete.')
            self._publish_status('mission_complete')
            return
            
        wp = self.waypoints[self.current_waypoint_index]
        name = wp.get('name', f'Waypoint_{self.current_waypoint_index}')
        self.get_logger().info(f"Sending goal for waypoint: '{name}'")
        self._publish_status('navigating')
        
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

        self._current_goal_handle = goal_handle
        self.get_logger().info('Nav2 accepted the goal, navigating...')
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        """Callback for goal completion."""
        self._current_goal_handle = None
        status = future.result().status

        if status == GoalStatus.STATUS_CANCELED:
            self.get_logger().info('Nav2 goal was cancelled.')
            return
        
        if status == GoalStatus.STATUS_SUCCEEDED:
            wp_name = self.waypoints[self.current_waypoint_index].get('name', '')
            self.get_logger().info(f"Successfully reached waypoint '{wp_name}'!")
            
            # Publish arrived exhibit message
            arrival_msg = String()
            arrival_msg.data = wp_name
            self.arrival_pub.publish(arrival_msg)
            self._publish_status('waiting')
            
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
        """Callback for trigger topic (direct from live_horus)."""
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

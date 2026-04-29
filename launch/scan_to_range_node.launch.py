import os

from ament_index_python.packages import get_package_share_directory


from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from launch_ros.actions import Node



def generate_launch_description():
    # Get the path to the current package
    pkg_articubot_one = 'articubot_one'
    us_center_converter = Node(
        package='articubot_one',
        executable='scan_to_range_node.py', # Name defined in setup.py
        name='us_center_converter',
        remappings=[
            ('/us_center/scan', '/us_center/scan'),
            ('/us_center/range', '/us_center/range')
        ]
    )

    # Left Sensor Converter
    us_left_converter = Node(
        package='articubot_one',
        executable='scan_to_range_node.py',
        name='us_left_converter',
        remappings=[
            ('/us_center/scan', '/us_left/scan'),
            ('/us_center/range', '/us_left/range')
        ]
    )

    # Right Sensor Converter
    us_right_converter = Node(
        package='articubot_one',
        executable='scan_to_range_node.py',
        name='us_right_converter',
        remappings=[
            ('/us_center/scan', '/us_right/scan'),
            ('/us_center/range', '/us_right/range')
        ]
    )
    return LaunchDescription([
        us_center_converter,
        us_left_converter,
        us_right_converter
])

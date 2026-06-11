"""
Unified Laptop Launch File
===========================
Launches everything that runs on the laptop:
  1. Localization (map_server + AMCL)  — immediately
  2. Navigation (Nav2 stack)           — after 10s delay

Usage:
  ros2 launch articubot_one bringup_laptop.launch.py
  ros2 launch articubot_one bringup_laptop.launch.py map:=/absolute/path/to/your_map.yaml
"""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    TimerAction,
    LogInfo,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():

    package_name = 'articubot_one'
    pkg_dir = get_package_share_directory(package_name)
    launch_dir = os.path.join(pkg_dir, 'launch')

    # ── Launch arguments ──────────────────────────
    map_yaml_file = LaunchConfiguration('map')
    use_sim_time = LaunchConfiguration('use_sim_time')

    declare_map_cmd = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_dir, 'maps', 'simplesave.yaml'),
        description='Full path to the map yaml file to load')

    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation (Gazebo) clock if true')

    # ──────────────────────────────────────────────
    # 1. Localization (launches immediately)
    # ──────────────────────────────────────────────
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'localization_launch.py')
        ),
        launch_arguments={
            'map': map_yaml_file,
            'use_sim_time': use_sim_time,
        }.items()
    )

    # ──────────────────────────────────────────────
    # 2. Navigation (delayed 10 s for AMCL to init)
    # ──────────────────────────────────────────────
    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'navigation_launch.py')
        ),
        launch_arguments={
            'use_sim_time': use_sim_time,
        }.items()
    )

    delayed_navigation = TimerAction(
        period=5.0,
        actions=[
            LogInfo(msg='>>> Starting Nav2 navigation stack...'),
            navigation,
        ]
    )

    return LaunchDescription([
        LogInfo(msg='========================================'),
        LogInfo(msg='  Articubot Bringup — Laptop'),
        LogInfo(msg='========================================'),

        # Declare arguments
        declare_map_cmd,
        declare_use_sim_time_cmd,

        # Launch in sequence
        LogInfo(msg='>>> Starting localization (map_server + AMCL)...'),
        localization,
        delayed_navigation,
    ])

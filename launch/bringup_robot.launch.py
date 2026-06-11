"""
Unified Raspberry Pi Launch File
================================
Launches everything that runs on the robot (Raspberry Pi):
  1. Robot hardware (RSP + controllers + twist_mux)  — immediately
  2. RPLidar node                                    — after 5s delay

Usage:
  ros2 launch articubot_one bringup_robot.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():

    package_name = 'articubot_one'
    pkg_dir = get_package_share_directory(package_name)
    launch_dir = os.path.join(pkg_dir, 'launch')

    # ──────────────────────────────────────────────
    # 1. Robot hardware (launches immediately)
    # ──────────────────────────────────────────────
    launch_robot = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'launch_robot.launch.py')
        )
    )

    # ──────────────────────────────────────────────
    # 2. RPLidar (delayed 5 s to let hardware init)
    # ──────────────────────────────────────────────
    rplidar = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'rplidar.launch.py')
        )
    )

    delayed_rplidar = TimerAction(
        period=5.0,
        actions=[
            LogInfo(msg='>>> Starting RPLidar node...'),
            rplidar,
        ]
    )

    return LaunchDescription([
        LogInfo(msg='========================================'),
        LogInfo(msg='  Articubot Bringup — Raspberry Pi'),
        LogInfo(msg='========================================'),
        LogInfo(msg='>>> Starting robot hardware...'),
        launch_robot,
        delayed_rplidar,
    ])

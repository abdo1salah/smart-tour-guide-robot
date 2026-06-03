import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    pkg_articubot_one = get_package_share_directory('articubot_one')

    map_file = LaunchConfiguration('map')
    
    declare_map_cmd = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_articubot_one, 'maps', 'my_map.yaml'),
        description='Full path to map file to load')

    localization_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(pkg_articubot_one, 'launch', 'localization_launch.py')),
        launch_arguments={'map': map_file, 'use_sim_time': 'false'}.items()
    )

    navigation_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(pkg_articubot_one, 'launch', 'navigation_launch.py')),
        launch_arguments={'use_sim_time': 'false'}.items()
    )

    return LaunchDescription([
        declare_map_cmd,
        localization_cmd,
        navigation_cmd
    ])
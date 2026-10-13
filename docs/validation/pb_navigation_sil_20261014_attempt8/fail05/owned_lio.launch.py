# Owned sensing/localization only. No Gazebo, hardware driver, fakeVel or controller.
from launch import LaunchDescription
from launch_ros.actions import Node
def generate_launch_description():
    return LaunchDescription([
        Node(package='point_lio', executable='pointlio_mapping', namespace='red_sentry', parameters=[{'use_sim_time': True, 'common.lid_topic': 'livox/lidar', 'common.imu_topic': 'livox/imu', 'common.con_frame': False, 'common.cut_frame': False, 'common.time_diff_lidar_to_imu': 0.0, 'preprocess.lidar_type': 1, 'preprocess.scan_line': 4, 'preprocess.timestamp_unit': 3, 'mapping.imu_time_inte': 0.002, 'mapping.acc_norm': 9.81, 'mapping.extrinsic_est_en': False, 'mapping.extrinsic_T': [0.0, 0.0, 0.0], 'mapping.extrinsic_R': [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], 'mapping.gravity_init': [0.0, 0.0, -9.81], 'prior_pcd.enable': False, 'odometry.publish_odometry_without_downsample': False, 'publish.scan_publish_en': True, 'publish.tf_send_en': False, 'runtime_pos_log_enable': False, 'pcd_save.pcd_save_en': False, 'pb.expected_robot_id': 'red_sentry', 'pb.expected_episode': 0, 'pb.expected_binding_epoch': 1}], output='screen'),
        Node(package='loam_interface', executable='loam_interface_node', namespace='red_sentry', parameters=[{'use_sim_time':True,'state_estimation_topic':'aft_mapped_to_init','registered_scan_topic':'cloud_registered','odom_frame':'odom','base_frame':'base_link','lidar_frame':'livox_frame'}], output='screen'),
        Node(package='sensor_scan_generation', executable='sensor_scan_generation_node', namespace='red_sentry', parameters=[{'use_sim_time':True,'base_frame':'base_link','robot_base_frame':'base_link','lidar_frame':'livox_frame'}], output='screen'),
    ])

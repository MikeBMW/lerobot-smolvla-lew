from setuptools import setup

package_name = 'smolvla_grpc_bridge'

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='MikeBMW',
    maintainer_email='niyingxiang@126.com',
    description='ROS2-gRPC bridge for SmolVLA policy inference',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'bridge_node = smolvla_grpc_bridge.bridge_node:main',
        ],
    },
)

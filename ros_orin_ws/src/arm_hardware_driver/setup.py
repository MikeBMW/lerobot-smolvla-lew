from setuptools import setup

package_name = 'arm_hardware_driver'

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
    description='Jetson Orin arm hardware drivers for Z-MAX robot',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'camera_pub = arm_hardware_driver.camera_pub:main',
            'joint_state_pub = arm_hardware_driver.joint_state_pub:main',
            'action_sub = arm_hardware_driver.action_sub:main',
        ],
    },
)

import os
os.environ["ROS_DOMAIN_ID"] = "23"
import rclpy
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2, time

rclpy.init(args=[])
bridge = CvBridge()
node = rclpy.create_node("cap")
got = []

def cb(msg):
    img = bridge.imgmsg_to_cv2(msg, "bgr8")
    cv2.imwrite("/tmp/cam.jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    got.append(True)

node.create_subscription(Image, "/realsense/color/image_raw", cb, 1)
t0 = time.time()
while not got and time.time() - t0 < 10:
    rclpy.spin_once(node, timeout_sec=0.5)

if got:
    print("OK " + str(os.path.getsize("/tmp/cam.jpg")))
else:
    print("NO_FRAME")

node.destroy_node()
rclpy.shutdown()
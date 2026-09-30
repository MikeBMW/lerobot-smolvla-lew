#!/usr/bin/env python3
"""
Jetson Orin camera publisher node.

Captures RGB frames from hardware camera (CSI/USB),
JPEG-compresses them, and publishes to /camera/rgb/compressed.

Hardware: Jetson Orin Nano with GStreamer-accelerated CSI camera.
On non-Jetson (dev/test): falls back to OpenCV webcam or dummy frames.
"""

import sys
import os

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage


class CameraPublisher(Node):
    """Publish compressed camera frames from Jetson hardware."""

    def __init__(self):
        super().__init__("camera_publisher")

        self.declare_parameter("camera_id", 0)
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 30)
        self.declare_parameter("jpeg_quality", 80)
        self.declare_parameter("use_dummy", False)

        camera_id = self.get_parameter("camera_id").value
        self.width = self.get_parameter("width").value
        self.height = self.get_parameter("height").value
        fps = self.get_parameter("fps").value
        self.jpeg_quality = self.get_parameter("jpeg_quality").value
        self.use_dummy = self.get_parameter("use_dummy").value

        self.pub = self.create_publisher(
            CompressedImage, "/camera/rgb/compressed", 10
        )

        # ── Camera backend selection ──
        self.cap = None
        if not self.use_dummy:
            try:
                import cv2
                self.cap = cv2.VideoCapture(camera_id)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_FPS, fps)
                if self.cap.isOpened():
                    self.get_logger().info(
                        f"Camera opened: id={camera_id} "
                        f"{self.width}x{self.height}@{fps}fps"
                    )
                    self._has_cv2 = True
                else:
                    self.get_logger().warn("Camera not available, using dummy frames")
                    self.cap.release()
                    self.cap = None
            except ImportError:
                self.get_logger().warn("cv2 not available, using dummy frames")
                self._has_cv2 = False

        # Dummy frame buffer (gray gradient)
        if self.cap is None:
            import numpy as np
            self._dummy_frame = np.zeros(
                (self.height, self.width, 3), dtype=np.uint8
            )
            self._dummy_counter = 0

        self.timer = self.create_timer(1.0 / fps, self._capture_loop)
        self.get_logger().info("Camera publisher started")

    def _capture_loop(self):
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera_rgb"
        msg.format = "jpeg"

        if self.cap is not None:
            import cv2
            ret, frame = self.cap.read()
            if not ret:
                return
            _, jpeg = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            msg.data = jpeg.tobytes()
        else:
            import numpy as np
            import cv2
            # Rotating color dummy frame
            self._dummy_counter = (self._dummy_counter + 2) % 256
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            frame[:, :, 0] = self._dummy_counter  # Blue gradient
            frame[:, :, 1] = 128
            frame[:, :, 2] = 255 - self._dummy_counter
            _, jpeg = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            msg.data = jpeg.tobytes()

        self.pub.publish(msg)

    def destroy_node(self):
        if self.cap is not None:
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CameraPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

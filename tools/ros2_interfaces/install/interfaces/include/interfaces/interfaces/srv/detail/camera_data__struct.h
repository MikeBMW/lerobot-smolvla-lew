// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from interfaces:srv/CameraData.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__CAMERA_DATA__STRUCT_H_
#define INTERFACES__SRV__DETAIL__CAMERA_DATA__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

/// Struct defined in srv/CameraData in the package interfaces.
typedef struct interfaces__srv__CameraData_Request
{
  int32_t camera_id;
} interfaces__srv__CameraData_Request;

// Struct for a sequence of interfaces__srv__CameraData_Request.
typedef struct interfaces__srv__CameraData_Request__Sequence
{
  interfaces__srv__CameraData_Request * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} interfaces__srv__CameraData_Request__Sequence;


// Constants defined in the message

// Include directives for member types
// Member 'normal_points'
#include "sensor_msgs/msg/detail/point_cloud2__struct.h"

/// Struct defined in srv/CameraData in the package interfaces.
typedef struct interfaces__srv__CameraData_Response
{
  sensor_msgs__msg__PointCloud2 normal_points;
} interfaces__srv__CameraData_Response;

// Struct for a sequence of interfaces__srv__CameraData_Response.
typedef struct interfaces__srv__CameraData_Response__Sequence
{
  interfaces__srv__CameraData_Response * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} interfaces__srv__CameraData_Response__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // INTERFACES__SRV__DETAIL__CAMERA_DATA__STRUCT_H_

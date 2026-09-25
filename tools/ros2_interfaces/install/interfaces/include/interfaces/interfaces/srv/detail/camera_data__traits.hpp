// generated from rosidl_generator_cpp/resource/idl__traits.hpp.em
// with input from interfaces:srv/CameraData.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__CAMERA_DATA__TRAITS_HPP_
#define INTERFACES__SRV__DETAIL__CAMERA_DATA__TRAITS_HPP_

#include <stdint.h>

#include <sstream>
#include <string>
#include <type_traits>

#include "interfaces/srv/detail/camera_data__struct.hpp"
#include "rosidl_runtime_cpp/traits.hpp"

namespace interfaces
{

namespace srv
{

inline void to_flow_style_yaml(
  const CameraData_Request & msg,
  std::ostream & out)
{
  out << "{";
  // member: camera_id
  {
    out << "camera_id: ";
    rosidl_generator_traits::value_to_yaml(msg.camera_id, out);
  }
  out << "}";
}  // NOLINT(readability/fn_size)

inline void to_block_style_yaml(
  const CameraData_Request & msg,
  std::ostream & out, size_t indentation = 0)
{
  // member: camera_id
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "camera_id: ";
    rosidl_generator_traits::value_to_yaml(msg.camera_id, out);
    out << "\n";
  }
}  // NOLINT(readability/fn_size)

inline std::string to_yaml(const CameraData_Request & msg, bool use_flow_style = false)
{
  std::ostringstream out;
  if (use_flow_style) {
    to_flow_style_yaml(msg, out);
  } else {
    to_block_style_yaml(msg, out);
  }
  return out.str();
}

}  // namespace srv

}  // namespace interfaces

namespace rosidl_generator_traits
{

[[deprecated("use interfaces::srv::to_block_style_yaml() instead")]]
inline void to_yaml(
  const interfaces::srv::CameraData_Request & msg,
  std::ostream & out, size_t indentation = 0)
{
  interfaces::srv::to_block_style_yaml(msg, out, indentation);
}

[[deprecated("use interfaces::srv::to_yaml() instead")]]
inline std::string to_yaml(const interfaces::srv::CameraData_Request & msg)
{
  return interfaces::srv::to_yaml(msg);
}

template<>
inline const char * data_type<interfaces::srv::CameraData_Request>()
{
  return "interfaces::srv::CameraData_Request";
}

template<>
inline const char * name<interfaces::srv::CameraData_Request>()
{
  return "interfaces/srv/CameraData_Request";
}

template<>
struct has_fixed_size<interfaces::srv::CameraData_Request>
  : std::integral_constant<bool, true> {};

template<>
struct has_bounded_size<interfaces::srv::CameraData_Request>
  : std::integral_constant<bool, true> {};

template<>
struct is_message<interfaces::srv::CameraData_Request>
  : std::true_type {};

}  // namespace rosidl_generator_traits

// Include directives for member types
// Member 'normal_points'
#include "sensor_msgs/msg/detail/point_cloud2__traits.hpp"

namespace interfaces
{

namespace srv
{

inline void to_flow_style_yaml(
  const CameraData_Response & msg,
  std::ostream & out)
{
  out << "{";
  // member: normal_points
  {
    out << "normal_points: ";
    to_flow_style_yaml(msg.normal_points, out);
  }
  out << "}";
}  // NOLINT(readability/fn_size)

inline void to_block_style_yaml(
  const CameraData_Response & msg,
  std::ostream & out, size_t indentation = 0)
{
  // member: normal_points
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "normal_points:\n";
    to_block_style_yaml(msg.normal_points, out, indentation + 2);
  }
}  // NOLINT(readability/fn_size)

inline std::string to_yaml(const CameraData_Response & msg, bool use_flow_style = false)
{
  std::ostringstream out;
  if (use_flow_style) {
    to_flow_style_yaml(msg, out);
  } else {
    to_block_style_yaml(msg, out);
  }
  return out.str();
}

}  // namespace srv

}  // namespace interfaces

namespace rosidl_generator_traits
{

[[deprecated("use interfaces::srv::to_block_style_yaml() instead")]]
inline void to_yaml(
  const interfaces::srv::CameraData_Response & msg,
  std::ostream & out, size_t indentation = 0)
{
  interfaces::srv::to_block_style_yaml(msg, out, indentation);
}

[[deprecated("use interfaces::srv::to_yaml() instead")]]
inline std::string to_yaml(const interfaces::srv::CameraData_Response & msg)
{
  return interfaces::srv::to_yaml(msg);
}

template<>
inline const char * data_type<interfaces::srv::CameraData_Response>()
{
  return "interfaces::srv::CameraData_Response";
}

template<>
inline const char * name<interfaces::srv::CameraData_Response>()
{
  return "interfaces/srv/CameraData_Response";
}

template<>
struct has_fixed_size<interfaces::srv::CameraData_Response>
  : std::integral_constant<bool, has_fixed_size<sensor_msgs::msg::PointCloud2>::value> {};

template<>
struct has_bounded_size<interfaces::srv::CameraData_Response>
  : std::integral_constant<bool, has_bounded_size<sensor_msgs::msg::PointCloud2>::value> {};

template<>
struct is_message<interfaces::srv::CameraData_Response>
  : std::true_type {};

}  // namespace rosidl_generator_traits

namespace rosidl_generator_traits
{

template<>
inline const char * data_type<interfaces::srv::CameraData>()
{
  return "interfaces::srv::CameraData";
}

template<>
inline const char * name<interfaces::srv::CameraData>()
{
  return "interfaces/srv/CameraData";
}

template<>
struct has_fixed_size<interfaces::srv::CameraData>
  : std::integral_constant<
    bool,
    has_fixed_size<interfaces::srv::CameraData_Request>::value &&
    has_fixed_size<interfaces::srv::CameraData_Response>::value
  >
{
};

template<>
struct has_bounded_size<interfaces::srv::CameraData>
  : std::integral_constant<
    bool,
    has_bounded_size<interfaces::srv::CameraData_Request>::value &&
    has_bounded_size<interfaces::srv::CameraData_Response>::value
  >
{
};

template<>
struct is_service<interfaces::srv::CameraData>
  : std::true_type
{
};

template<>
struct is_service_request<interfaces::srv::CameraData_Request>
  : std::true_type
{
};

template<>
struct is_service_response<interfaces::srv::CameraData_Response>
  : std::true_type
{
};

}  // namespace rosidl_generator_traits

#endif  // INTERFACES__SRV__DETAIL__CAMERA_DATA__TRAITS_HPP_

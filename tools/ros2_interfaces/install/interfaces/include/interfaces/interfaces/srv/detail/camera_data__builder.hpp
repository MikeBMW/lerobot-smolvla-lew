// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from interfaces:srv/CameraData.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__CAMERA_DATA__BUILDER_HPP_
#define INTERFACES__SRV__DETAIL__CAMERA_DATA__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "interfaces/srv/detail/camera_data__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace interfaces
{

namespace srv
{

namespace builder
{

class Init_CameraData_Request_camera_id
{
public:
  Init_CameraData_Request_camera_id()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  ::interfaces::srv::CameraData_Request camera_id(::interfaces::srv::CameraData_Request::_camera_id_type arg)
  {
    msg_.camera_id = std::move(arg);
    return std::move(msg_);
  }

private:
  ::interfaces::srv::CameraData_Request msg_;
};

}  // namespace builder

}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::interfaces::srv::CameraData_Request>()
{
  return interfaces::srv::builder::Init_CameraData_Request_camera_id();
}

}  // namespace interfaces


namespace interfaces
{

namespace srv
{

namespace builder
{

class Init_CameraData_Response_normal_points
{
public:
  Init_CameraData_Response_normal_points()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  ::interfaces::srv::CameraData_Response normal_points(::interfaces::srv::CameraData_Response::_normal_points_type arg)
  {
    msg_.normal_points = std::move(arg);
    return std::move(msg_);
  }

private:
  ::interfaces::srv::CameraData_Response msg_;
};

}  // namespace builder

}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::interfaces::srv::CameraData_Response>()
{
  return interfaces::srv::builder::Init_CameraData_Response_normal_points();
}

}  // namespace interfaces

#endif  // INTERFACES__SRV__DETAIL__CAMERA_DATA__BUILDER_HPP_

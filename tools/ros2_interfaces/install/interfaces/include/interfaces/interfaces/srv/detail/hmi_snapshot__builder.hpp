// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from interfaces:srv/HmiSnapshot.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__HMI_SNAPSHOT__BUILDER_HPP_
#define INTERFACES__SRV__DETAIL__HMI_SNAPSHOT__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "interfaces/srv/detail/hmi_snapshot__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace interfaces
{

namespace srv
{


}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::interfaces::srv::HmiSnapshot_Request>()
{
  return ::interfaces::srv::HmiSnapshot_Request(rosidl_runtime_cpp::MessageInitialization::ZERO);
}

}  // namespace interfaces


namespace interfaces
{

namespace srv
{

namespace builder
{

class Init_HmiSnapshot_Response_snapshot_json
{
public:
  explicit Init_HmiSnapshot_Response_snapshot_json(::interfaces::srv::HmiSnapshot_Response & msg)
  : msg_(msg)
  {}
  ::interfaces::srv::HmiSnapshot_Response snapshot_json(::interfaces::srv::HmiSnapshot_Response::_snapshot_json_type arg)
  {
    msg_.snapshot_json = std::move(arg);
    return std::move(msg_);
  }

private:
  ::interfaces::srv::HmiSnapshot_Response msg_;
};

class Init_HmiSnapshot_Response_message
{
public:
  explicit Init_HmiSnapshot_Response_message(::interfaces::srv::HmiSnapshot_Response & msg)
  : msg_(msg)
  {}
  Init_HmiSnapshot_Response_snapshot_json message(::interfaces::srv::HmiSnapshot_Response::_message_type arg)
  {
    msg_.message = std::move(arg);
    return Init_HmiSnapshot_Response_snapshot_json(msg_);
  }

private:
  ::interfaces::srv::HmiSnapshot_Response msg_;
};

class Init_HmiSnapshot_Response_success
{
public:
  Init_HmiSnapshot_Response_success()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_HmiSnapshot_Response_message success(::interfaces::srv::HmiSnapshot_Response::_success_type arg)
  {
    msg_.success = std::move(arg);
    return Init_HmiSnapshot_Response_message(msg_);
  }

private:
  ::interfaces::srv::HmiSnapshot_Response msg_;
};

}  // namespace builder

}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::interfaces::srv::HmiSnapshot_Response>()
{
  return interfaces::srv::builder::Init_HmiSnapshot_Response_success();
}

}  // namespace interfaces

#endif  // INTERFACES__SRV__DETAIL__HMI_SNAPSHOT__BUILDER_HPP_

// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from interfaces:srv/HmiCommand.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__HMI_COMMAND__BUILDER_HPP_
#define INTERFACES__SRV__DETAIL__HMI_COMMAND__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "interfaces/srv/detail/hmi_command__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace interfaces
{

namespace srv
{

namespace builder
{

class Init_HmiCommand_Request_payload_json
{
public:
  explicit Init_HmiCommand_Request_payload_json(::interfaces::srv::HmiCommand_Request & msg)
  : msg_(msg)
  {}
  ::interfaces::srv::HmiCommand_Request payload_json(::interfaces::srv::HmiCommand_Request::_payload_json_type arg)
  {
    msg_.payload_json = std::move(arg);
    return std::move(msg_);
  }

private:
  ::interfaces::srv::HmiCommand_Request msg_;
};

class Init_HmiCommand_Request_command_id
{
public:
  explicit Init_HmiCommand_Request_command_id(::interfaces::srv::HmiCommand_Request & msg)
  : msg_(msg)
  {}
  Init_HmiCommand_Request_payload_json command_id(::interfaces::srv::HmiCommand_Request::_command_id_type arg)
  {
    msg_.command_id = std::move(arg);
    return Init_HmiCommand_Request_payload_json(msg_);
  }

private:
  ::interfaces::srv::HmiCommand_Request msg_;
};

class Init_HmiCommand_Request_command
{
public:
  Init_HmiCommand_Request_command()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_HmiCommand_Request_command_id command(::interfaces::srv::HmiCommand_Request::_command_type arg)
  {
    msg_.command = std::move(arg);
    return Init_HmiCommand_Request_command_id(msg_);
  }

private:
  ::interfaces::srv::HmiCommand_Request msg_;
};

}  // namespace builder

}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::interfaces::srv::HmiCommand_Request>()
{
  return interfaces::srv::builder::Init_HmiCommand_Request_command();
}

}  // namespace interfaces


namespace interfaces
{

namespace srv
{

namespace builder
{

class Init_HmiCommand_Response_result_json
{
public:
  explicit Init_HmiCommand_Response_result_json(::interfaces::srv::HmiCommand_Response & msg)
  : msg_(msg)
  {}
  ::interfaces::srv::HmiCommand_Response result_json(::interfaces::srv::HmiCommand_Response::_result_json_type arg)
  {
    msg_.result_json = std::move(arg);
    return std::move(msg_);
  }

private:
  ::interfaces::srv::HmiCommand_Response msg_;
};

class Init_HmiCommand_Response_message
{
public:
  explicit Init_HmiCommand_Response_message(::interfaces::srv::HmiCommand_Response & msg)
  : msg_(msg)
  {}
  Init_HmiCommand_Response_result_json message(::interfaces::srv::HmiCommand_Response::_message_type arg)
  {
    msg_.message = std::move(arg);
    return Init_HmiCommand_Response_result_json(msg_);
  }

private:
  ::interfaces::srv::HmiCommand_Response msg_;
};

class Init_HmiCommand_Response_success
{
public:
  Init_HmiCommand_Response_success()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_HmiCommand_Response_message success(::interfaces::srv::HmiCommand_Response::_success_type arg)
  {
    msg_.success = std::move(arg);
    return Init_HmiCommand_Response_message(msg_);
  }

private:
  ::interfaces::srv::HmiCommand_Response msg_;
};

}  // namespace builder

}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::interfaces::srv::HmiCommand_Response>()
{
  return interfaces::srv::builder::Init_HmiCommand_Response_success();
}

}  // namespace interfaces

#endif  // INTERFACES__SRV__DETAIL__HMI_COMMAND__BUILDER_HPP_

// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from interfaces:srv/HmiCommand.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__HMI_COMMAND__STRUCT_H_
#define INTERFACES__SRV__DETAIL__HMI_COMMAND__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

// Include directives for member types
// Member 'command'
// Member 'command_id'
// Member 'payload_json'
#include "rosidl_runtime_c/string.h"

/// Struct defined in srv/HmiCommand in the package interfaces.
typedef struct interfaces__srv__HmiCommand_Request
{
  rosidl_runtime_c__String command;
  rosidl_runtime_c__String command_id;
  rosidl_runtime_c__String payload_json;
} interfaces__srv__HmiCommand_Request;

// Struct for a sequence of interfaces__srv__HmiCommand_Request.
typedef struct interfaces__srv__HmiCommand_Request__Sequence
{
  interfaces__srv__HmiCommand_Request * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} interfaces__srv__HmiCommand_Request__Sequence;


// Constants defined in the message

// Include directives for member types
// Member 'message'
// Member 'result_json'
// already included above
// #include "rosidl_runtime_c/string.h"

/// Struct defined in srv/HmiCommand in the package interfaces.
typedef struct interfaces__srv__HmiCommand_Response
{
  bool success;
  rosidl_runtime_c__String message;
  rosidl_runtime_c__String result_json;
} interfaces__srv__HmiCommand_Response;

// Struct for a sequence of interfaces__srv__HmiCommand_Response.
typedef struct interfaces__srv__HmiCommand_Response__Sequence
{
  interfaces__srv__HmiCommand_Response * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} interfaces__srv__HmiCommand_Response__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // INTERFACES__SRV__DETAIL__HMI_COMMAND__STRUCT_H_

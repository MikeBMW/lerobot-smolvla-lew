// generated from rosidl_generator_cpp/resource/idl__struct.hpp.em
// with input from interfaces:srv/HmiSnapshot.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__HMI_SNAPSHOT__STRUCT_HPP_
#define INTERFACES__SRV__DETAIL__HMI_SNAPSHOT__STRUCT_HPP_

#include <algorithm>
#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "rosidl_runtime_cpp/bounded_vector.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


#ifndef _WIN32
# define DEPRECATED__interfaces__srv__HmiSnapshot_Request __attribute__((deprecated))
#else
# define DEPRECATED__interfaces__srv__HmiSnapshot_Request __declspec(deprecated)
#endif

namespace interfaces
{

namespace srv
{

// message struct
template<class ContainerAllocator>
struct HmiSnapshot_Request_
{
  using Type = HmiSnapshot_Request_<ContainerAllocator>;

  explicit HmiSnapshot_Request_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->structure_needs_at_least_one_member = 0;
    }
  }

  explicit HmiSnapshot_Request_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    (void)_alloc;
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->structure_needs_at_least_one_member = 0;
    }
  }

  // field types and members
  using _structure_needs_at_least_one_member_type =
    uint8_t;
  _structure_needs_at_least_one_member_type structure_needs_at_least_one_member;


  // constant declarations

  // pointer types
  using RawPtr =
    interfaces::srv::HmiSnapshot_Request_<ContainerAllocator> *;
  using ConstRawPtr =
    const interfaces::srv::HmiSnapshot_Request_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::HmiSnapshot_Request_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::HmiSnapshot_Request_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__interfaces__srv__HmiSnapshot_Request
    std::shared_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__interfaces__srv__HmiSnapshot_Request
    std::shared_ptr<interfaces::srv::HmiSnapshot_Request_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const HmiSnapshot_Request_ & other) const
  {
    if (this->structure_needs_at_least_one_member != other.structure_needs_at_least_one_member) {
      return false;
    }
    return true;
  }
  bool operator!=(const HmiSnapshot_Request_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct HmiSnapshot_Request_

// alias to use template instance with default allocator
using HmiSnapshot_Request =
  interfaces::srv::HmiSnapshot_Request_<std::allocator<void>>;

// constant definitions

}  // namespace srv

}  // namespace interfaces


#ifndef _WIN32
# define DEPRECATED__interfaces__srv__HmiSnapshot_Response __attribute__((deprecated))
#else
# define DEPRECATED__interfaces__srv__HmiSnapshot_Response __declspec(deprecated)
#endif

namespace interfaces
{

namespace srv
{

// message struct
template<class ContainerAllocator>
struct HmiSnapshot_Response_
{
  using Type = HmiSnapshot_Response_<ContainerAllocator>;

  explicit HmiSnapshot_Response_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->success = false;
      this->message = "";
      this->snapshot_json = "";
    }
  }

  explicit HmiSnapshot_Response_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  : message(_alloc),
    snapshot_json(_alloc)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->success = false;
      this->message = "";
      this->snapshot_json = "";
    }
  }

  // field types and members
  using _success_type =
    bool;
  _success_type success;
  using _message_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _message_type message;
  using _snapshot_json_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _snapshot_json_type snapshot_json;

  // setters for named parameter idiom
  Type & set__success(
    const bool & _arg)
  {
    this->success = _arg;
    return *this;
  }
  Type & set__message(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->message = _arg;
    return *this;
  }
  Type & set__snapshot_json(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->snapshot_json = _arg;
    return *this;
  }

  // constant declarations

  // pointer types
  using RawPtr =
    interfaces::srv::HmiSnapshot_Response_<ContainerAllocator> *;
  using ConstRawPtr =
    const interfaces::srv::HmiSnapshot_Response_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::HmiSnapshot_Response_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::HmiSnapshot_Response_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__interfaces__srv__HmiSnapshot_Response
    std::shared_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__interfaces__srv__HmiSnapshot_Response
    std::shared_ptr<interfaces::srv::HmiSnapshot_Response_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const HmiSnapshot_Response_ & other) const
  {
    if (this->success != other.success) {
      return false;
    }
    if (this->message != other.message) {
      return false;
    }
    if (this->snapshot_json != other.snapshot_json) {
      return false;
    }
    return true;
  }
  bool operator!=(const HmiSnapshot_Response_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct HmiSnapshot_Response_

// alias to use template instance with default allocator
using HmiSnapshot_Response =
  interfaces::srv::HmiSnapshot_Response_<std::allocator<void>>;

// constant definitions

}  // namespace srv

}  // namespace interfaces

namespace interfaces
{

namespace srv
{

struct HmiSnapshot
{
  using Request = interfaces::srv::HmiSnapshot_Request;
  using Response = interfaces::srv::HmiSnapshot_Response;
};

}  // namespace srv

}  // namespace interfaces

#endif  // INTERFACES__SRV__DETAIL__HMI_SNAPSHOT__STRUCT_HPP_

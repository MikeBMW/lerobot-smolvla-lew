// generated from rosidl_generator_cpp/resource/idl__struct.hpp.em
// with input from interfaces:srv/CameraData.idl
// generated code does not contain a copyright notice

#ifndef INTERFACES__SRV__DETAIL__CAMERA_DATA__STRUCT_HPP_
#define INTERFACES__SRV__DETAIL__CAMERA_DATA__STRUCT_HPP_

#include <algorithm>
#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "rosidl_runtime_cpp/bounded_vector.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


#ifndef _WIN32
# define DEPRECATED__interfaces__srv__CameraData_Request __attribute__((deprecated))
#else
# define DEPRECATED__interfaces__srv__CameraData_Request __declspec(deprecated)
#endif

namespace interfaces
{

namespace srv
{

// message struct
template<class ContainerAllocator>
struct CameraData_Request_
{
  using Type = CameraData_Request_<ContainerAllocator>;

  explicit CameraData_Request_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->camera_id = 0l;
    }
  }

  explicit CameraData_Request_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    (void)_alloc;
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->camera_id = 0l;
    }
  }

  // field types and members
  using _camera_id_type =
    int32_t;
  _camera_id_type camera_id;

  // setters for named parameter idiom
  Type & set__camera_id(
    const int32_t & _arg)
  {
    this->camera_id = _arg;
    return *this;
  }

  // constant declarations

  // pointer types
  using RawPtr =
    interfaces::srv::CameraData_Request_<ContainerAllocator> *;
  using ConstRawPtr =
    const interfaces::srv::CameraData_Request_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::CameraData_Request_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::CameraData_Request_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__interfaces__srv__CameraData_Request
    std::shared_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__interfaces__srv__CameraData_Request
    std::shared_ptr<interfaces::srv::CameraData_Request_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const CameraData_Request_ & other) const
  {
    if (this->camera_id != other.camera_id) {
      return false;
    }
    return true;
  }
  bool operator!=(const CameraData_Request_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct CameraData_Request_

// alias to use template instance with default allocator
using CameraData_Request =
  interfaces::srv::CameraData_Request_<std::allocator<void>>;

// constant definitions

}  // namespace srv

}  // namespace interfaces


// Include directives for member types
// Member 'normal_points'
#include "sensor_msgs/msg/detail/point_cloud2__struct.hpp"

#ifndef _WIN32
# define DEPRECATED__interfaces__srv__CameraData_Response __attribute__((deprecated))
#else
# define DEPRECATED__interfaces__srv__CameraData_Response __declspec(deprecated)
#endif

namespace interfaces
{

namespace srv
{

// message struct
template<class ContainerAllocator>
struct CameraData_Response_
{
  using Type = CameraData_Response_<ContainerAllocator>;

  explicit CameraData_Response_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  : normal_points(_init)
  {
    (void)_init;
  }

  explicit CameraData_Response_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  : normal_points(_alloc, _init)
  {
    (void)_init;
  }

  // field types and members
  using _normal_points_type =
    sensor_msgs::msg::PointCloud2_<ContainerAllocator>;
  _normal_points_type normal_points;

  // setters for named parameter idiom
  Type & set__normal_points(
    const sensor_msgs::msg::PointCloud2_<ContainerAllocator> & _arg)
  {
    this->normal_points = _arg;
    return *this;
  }

  // constant declarations

  // pointer types
  using RawPtr =
    interfaces::srv::CameraData_Response_<ContainerAllocator> *;
  using ConstRawPtr =
    const interfaces::srv::CameraData_Response_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::CameraData_Response_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      interfaces::srv::CameraData_Response_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__interfaces__srv__CameraData_Response
    std::shared_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__interfaces__srv__CameraData_Response
    std::shared_ptr<interfaces::srv::CameraData_Response_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const CameraData_Response_ & other) const
  {
    if (this->normal_points != other.normal_points) {
      return false;
    }
    return true;
  }
  bool operator!=(const CameraData_Response_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct CameraData_Response_

// alias to use template instance with default allocator
using CameraData_Response =
  interfaces::srv::CameraData_Response_<std::allocator<void>>;

// constant definitions

}  // namespace srv

}  // namespace interfaces

namespace interfaces
{

namespace srv
{

struct CameraData
{
  using Request = interfaces::srv::CameraData_Request;
  using Response = interfaces::srv::CameraData_Response;
};

}  // namespace srv

}  // namespace interfaces

#endif  // INTERFACES__SRV__DETAIL__CAMERA_DATA__STRUCT_HPP_

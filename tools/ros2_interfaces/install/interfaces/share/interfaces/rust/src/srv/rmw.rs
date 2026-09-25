#[cfg(feature = "serde")]
use serde::{Deserialize, Serialize};



#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiSnapshot_Request() -> *const std::ffi::c_void;
}

#[link(name = "interfaces__rosidl_generator_c")]
extern "C" {
    fn interfaces__srv__HmiSnapshot_Request__init(msg: *mut HmiSnapshot_Request) -> bool;
    fn interfaces__srv__HmiSnapshot_Request__Sequence__init(seq: *mut rosidl_runtime_rs::Sequence<HmiSnapshot_Request>, size: usize) -> bool;
    fn interfaces__srv__HmiSnapshot_Request__Sequence__fini(seq: *mut rosidl_runtime_rs::Sequence<HmiSnapshot_Request>);
    fn interfaces__srv__HmiSnapshot_Request__Sequence__copy(in_seq: &rosidl_runtime_rs::Sequence<HmiSnapshot_Request>, out_seq: *mut rosidl_runtime_rs::Sequence<HmiSnapshot_Request>) -> bool;
}

// Corresponds to interfaces__srv__HmiSnapshot_Request
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]


// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiSnapshot_Request {

    // This member is not documented.
    #[allow(missing_docs)]
    pub structure_needs_at_least_one_member: u8,

}



impl Default for HmiSnapshot_Request {
  fn default() -> Self {
    unsafe {
      let mut msg = std::mem::zeroed();
      if !interfaces__srv__HmiSnapshot_Request__init(&mut msg as *mut _) {
        panic!("Call to interfaces__srv__HmiSnapshot_Request__init() failed");
      }
      msg
    }
  }
}

impl rosidl_runtime_rs::SequenceAlloc for HmiSnapshot_Request {
  fn sequence_init(seq: &mut rosidl_runtime_rs::Sequence<Self>, size: usize) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiSnapshot_Request__Sequence__init(seq as *mut _, size) }
  }
  fn sequence_fini(seq: &mut rosidl_runtime_rs::Sequence<Self>) {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiSnapshot_Request__Sequence__fini(seq as *mut _) }
  }
  fn sequence_copy(in_seq: &rosidl_runtime_rs::Sequence<Self>, out_seq: &mut rosidl_runtime_rs::Sequence<Self>) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiSnapshot_Request__Sequence__copy(in_seq, out_seq as *mut _) }
  }
}

impl rosidl_runtime_rs::Message for HmiSnapshot_Request {
  type RmwMsg = Self;
  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> { msg_cow }
  fn from_rmw_message(msg: Self::RmwMsg) -> Self { msg }
}

impl rosidl_runtime_rs::RmwMessage for HmiSnapshot_Request where Self: Sized {
  const TYPE_NAME: &'static str = "interfaces/srv/HmiSnapshot_Request";
  fn get_type_support() -> *const std::ffi::c_void {
    // SAFETY: No preconditions for this function.
    unsafe { rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiSnapshot_Request() }
  }
}


#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiSnapshot_Response() -> *const std::ffi::c_void;
}

#[link(name = "interfaces__rosidl_generator_c")]
extern "C" {
    fn interfaces__srv__HmiSnapshot_Response__init(msg: *mut HmiSnapshot_Response) -> bool;
    fn interfaces__srv__HmiSnapshot_Response__Sequence__init(seq: *mut rosidl_runtime_rs::Sequence<HmiSnapshot_Response>, size: usize) -> bool;
    fn interfaces__srv__HmiSnapshot_Response__Sequence__fini(seq: *mut rosidl_runtime_rs::Sequence<HmiSnapshot_Response>);
    fn interfaces__srv__HmiSnapshot_Response__Sequence__copy(in_seq: &rosidl_runtime_rs::Sequence<HmiSnapshot_Response>, out_seq: *mut rosidl_runtime_rs::Sequence<HmiSnapshot_Response>) -> bool;
}

// Corresponds to interfaces__srv__HmiSnapshot_Response
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]


// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiSnapshot_Response {

    // This member is not documented.
    #[allow(missing_docs)]
    pub success: bool,


    // This member is not documented.
    #[allow(missing_docs)]
    pub message: rosidl_runtime_rs::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub snapshot_json: rosidl_runtime_rs::String,

}



impl Default for HmiSnapshot_Response {
  fn default() -> Self {
    unsafe {
      let mut msg = std::mem::zeroed();
      if !interfaces__srv__HmiSnapshot_Response__init(&mut msg as *mut _) {
        panic!("Call to interfaces__srv__HmiSnapshot_Response__init() failed");
      }
      msg
    }
  }
}

impl rosidl_runtime_rs::SequenceAlloc for HmiSnapshot_Response {
  fn sequence_init(seq: &mut rosidl_runtime_rs::Sequence<Self>, size: usize) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiSnapshot_Response__Sequence__init(seq as *mut _, size) }
  }
  fn sequence_fini(seq: &mut rosidl_runtime_rs::Sequence<Self>) {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiSnapshot_Response__Sequence__fini(seq as *mut _) }
  }
  fn sequence_copy(in_seq: &rosidl_runtime_rs::Sequence<Self>, out_seq: &mut rosidl_runtime_rs::Sequence<Self>) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiSnapshot_Response__Sequence__copy(in_seq, out_seq as *mut _) }
  }
}

impl rosidl_runtime_rs::Message for HmiSnapshot_Response {
  type RmwMsg = Self;
  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> { msg_cow }
  fn from_rmw_message(msg: Self::RmwMsg) -> Self { msg }
}

impl rosidl_runtime_rs::RmwMessage for HmiSnapshot_Response where Self: Sized {
  const TYPE_NAME: &'static str = "interfaces/srv/HmiSnapshot_Response";
  fn get_type_support() -> *const std::ffi::c_void {
    // SAFETY: No preconditions for this function.
    unsafe { rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiSnapshot_Response() }
  }
}


#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiCommand_Request() -> *const std::ffi::c_void;
}

#[link(name = "interfaces__rosidl_generator_c")]
extern "C" {
    fn interfaces__srv__HmiCommand_Request__init(msg: *mut HmiCommand_Request) -> bool;
    fn interfaces__srv__HmiCommand_Request__Sequence__init(seq: *mut rosidl_runtime_rs::Sequence<HmiCommand_Request>, size: usize) -> bool;
    fn interfaces__srv__HmiCommand_Request__Sequence__fini(seq: *mut rosidl_runtime_rs::Sequence<HmiCommand_Request>);
    fn interfaces__srv__HmiCommand_Request__Sequence__copy(in_seq: &rosidl_runtime_rs::Sequence<HmiCommand_Request>, out_seq: *mut rosidl_runtime_rs::Sequence<HmiCommand_Request>) -> bool;
}

// Corresponds to interfaces__srv__HmiCommand_Request
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]


// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiCommand_Request {

    // This member is not documented.
    #[allow(missing_docs)]
    pub command: rosidl_runtime_rs::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub command_id: rosidl_runtime_rs::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub payload_json: rosidl_runtime_rs::String,

}



impl Default for HmiCommand_Request {
  fn default() -> Self {
    unsafe {
      let mut msg = std::mem::zeroed();
      if !interfaces__srv__HmiCommand_Request__init(&mut msg as *mut _) {
        panic!("Call to interfaces__srv__HmiCommand_Request__init() failed");
      }
      msg
    }
  }
}

impl rosidl_runtime_rs::SequenceAlloc for HmiCommand_Request {
  fn sequence_init(seq: &mut rosidl_runtime_rs::Sequence<Self>, size: usize) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiCommand_Request__Sequence__init(seq as *mut _, size) }
  }
  fn sequence_fini(seq: &mut rosidl_runtime_rs::Sequence<Self>) {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiCommand_Request__Sequence__fini(seq as *mut _) }
  }
  fn sequence_copy(in_seq: &rosidl_runtime_rs::Sequence<Self>, out_seq: &mut rosidl_runtime_rs::Sequence<Self>) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiCommand_Request__Sequence__copy(in_seq, out_seq as *mut _) }
  }
}

impl rosidl_runtime_rs::Message for HmiCommand_Request {
  type RmwMsg = Self;
  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> { msg_cow }
  fn from_rmw_message(msg: Self::RmwMsg) -> Self { msg }
}

impl rosidl_runtime_rs::RmwMessage for HmiCommand_Request where Self: Sized {
  const TYPE_NAME: &'static str = "interfaces/srv/HmiCommand_Request";
  fn get_type_support() -> *const std::ffi::c_void {
    // SAFETY: No preconditions for this function.
    unsafe { rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiCommand_Request() }
  }
}


#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiCommand_Response() -> *const std::ffi::c_void;
}

#[link(name = "interfaces__rosidl_generator_c")]
extern "C" {
    fn interfaces__srv__HmiCommand_Response__init(msg: *mut HmiCommand_Response) -> bool;
    fn interfaces__srv__HmiCommand_Response__Sequence__init(seq: *mut rosidl_runtime_rs::Sequence<HmiCommand_Response>, size: usize) -> bool;
    fn interfaces__srv__HmiCommand_Response__Sequence__fini(seq: *mut rosidl_runtime_rs::Sequence<HmiCommand_Response>);
    fn interfaces__srv__HmiCommand_Response__Sequence__copy(in_seq: &rosidl_runtime_rs::Sequence<HmiCommand_Response>, out_seq: *mut rosidl_runtime_rs::Sequence<HmiCommand_Response>) -> bool;
}

// Corresponds to interfaces__srv__HmiCommand_Response
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]


// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiCommand_Response {

    // This member is not documented.
    #[allow(missing_docs)]
    pub success: bool,


    // This member is not documented.
    #[allow(missing_docs)]
    pub message: rosidl_runtime_rs::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub result_json: rosidl_runtime_rs::String,

}



impl Default for HmiCommand_Response {
  fn default() -> Self {
    unsafe {
      let mut msg = std::mem::zeroed();
      if !interfaces__srv__HmiCommand_Response__init(&mut msg as *mut _) {
        panic!("Call to interfaces__srv__HmiCommand_Response__init() failed");
      }
      msg
    }
  }
}

impl rosidl_runtime_rs::SequenceAlloc for HmiCommand_Response {
  fn sequence_init(seq: &mut rosidl_runtime_rs::Sequence<Self>, size: usize) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiCommand_Response__Sequence__init(seq as *mut _, size) }
  }
  fn sequence_fini(seq: &mut rosidl_runtime_rs::Sequence<Self>) {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiCommand_Response__Sequence__fini(seq as *mut _) }
  }
  fn sequence_copy(in_seq: &rosidl_runtime_rs::Sequence<Self>, out_seq: &mut rosidl_runtime_rs::Sequence<Self>) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__HmiCommand_Response__Sequence__copy(in_seq, out_seq as *mut _) }
  }
}

impl rosidl_runtime_rs::Message for HmiCommand_Response {
  type RmwMsg = Self;
  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> { msg_cow }
  fn from_rmw_message(msg: Self::RmwMsg) -> Self { msg }
}

impl rosidl_runtime_rs::RmwMessage for HmiCommand_Response where Self: Sized {
  const TYPE_NAME: &'static str = "interfaces/srv/HmiCommand_Response";
  fn get_type_support() -> *const std::ffi::c_void {
    // SAFETY: No preconditions for this function.
    unsafe { rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__HmiCommand_Response() }
  }
}


#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__CameraData_Request() -> *const std::ffi::c_void;
}

#[link(name = "interfaces__rosidl_generator_c")]
extern "C" {
    fn interfaces__srv__CameraData_Request__init(msg: *mut CameraData_Request) -> bool;
    fn interfaces__srv__CameraData_Request__Sequence__init(seq: *mut rosidl_runtime_rs::Sequence<CameraData_Request>, size: usize) -> bool;
    fn interfaces__srv__CameraData_Request__Sequence__fini(seq: *mut rosidl_runtime_rs::Sequence<CameraData_Request>);
    fn interfaces__srv__CameraData_Request__Sequence__copy(in_seq: &rosidl_runtime_rs::Sequence<CameraData_Request>, out_seq: *mut rosidl_runtime_rs::Sequence<CameraData_Request>) -> bool;
}

// Corresponds to interfaces__srv__CameraData_Request
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]


// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct CameraData_Request {

    // This member is not documented.
    #[allow(missing_docs)]
    pub camera_id: i32,

}



impl Default for CameraData_Request {
  fn default() -> Self {
    unsafe {
      let mut msg = std::mem::zeroed();
      if !interfaces__srv__CameraData_Request__init(&mut msg as *mut _) {
        panic!("Call to interfaces__srv__CameraData_Request__init() failed");
      }
      msg
    }
  }
}

impl rosidl_runtime_rs::SequenceAlloc for CameraData_Request {
  fn sequence_init(seq: &mut rosidl_runtime_rs::Sequence<Self>, size: usize) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__CameraData_Request__Sequence__init(seq as *mut _, size) }
  }
  fn sequence_fini(seq: &mut rosidl_runtime_rs::Sequence<Self>) {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__CameraData_Request__Sequence__fini(seq as *mut _) }
  }
  fn sequence_copy(in_seq: &rosidl_runtime_rs::Sequence<Self>, out_seq: &mut rosidl_runtime_rs::Sequence<Self>) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__CameraData_Request__Sequence__copy(in_seq, out_seq as *mut _) }
  }
}

impl rosidl_runtime_rs::Message for CameraData_Request {
  type RmwMsg = Self;
  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> { msg_cow }
  fn from_rmw_message(msg: Self::RmwMsg) -> Self { msg }
}

impl rosidl_runtime_rs::RmwMessage for CameraData_Request where Self: Sized {
  const TYPE_NAME: &'static str = "interfaces/srv/CameraData_Request";
  fn get_type_support() -> *const std::ffi::c_void {
    // SAFETY: No preconditions for this function.
    unsafe { rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__CameraData_Request() }
  }
}


#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__CameraData_Response() -> *const std::ffi::c_void;
}

#[link(name = "interfaces__rosidl_generator_c")]
extern "C" {
    fn interfaces__srv__CameraData_Response__init(msg: *mut CameraData_Response) -> bool;
    fn interfaces__srv__CameraData_Response__Sequence__init(seq: *mut rosidl_runtime_rs::Sequence<CameraData_Response>, size: usize) -> bool;
    fn interfaces__srv__CameraData_Response__Sequence__fini(seq: *mut rosidl_runtime_rs::Sequence<CameraData_Response>);
    fn interfaces__srv__CameraData_Response__Sequence__copy(in_seq: &rosidl_runtime_rs::Sequence<CameraData_Response>, out_seq: *mut rosidl_runtime_rs::Sequence<CameraData_Response>) -> bool;
}

// Corresponds to interfaces__srv__CameraData_Response
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]


// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[repr(C)]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct CameraData_Response {

    // This member is not documented.
    #[allow(missing_docs)]
    pub normal_points: sensor_msgs::msg::rmw::PointCloud2,

}



impl Default for CameraData_Response {
  fn default() -> Self {
    unsafe {
      let mut msg = std::mem::zeroed();
      if !interfaces__srv__CameraData_Response__init(&mut msg as *mut _) {
        panic!("Call to interfaces__srv__CameraData_Response__init() failed");
      }
      msg
    }
  }
}

impl rosidl_runtime_rs::SequenceAlloc for CameraData_Response {
  fn sequence_init(seq: &mut rosidl_runtime_rs::Sequence<Self>, size: usize) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__CameraData_Response__Sequence__init(seq as *mut _, size) }
  }
  fn sequence_fini(seq: &mut rosidl_runtime_rs::Sequence<Self>) {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__CameraData_Response__Sequence__fini(seq as *mut _) }
  }
  fn sequence_copy(in_seq: &rosidl_runtime_rs::Sequence<Self>, out_seq: &mut rosidl_runtime_rs::Sequence<Self>) -> bool {
    // SAFETY: This is safe since the pointer is guaranteed to be valid/initialized.
    unsafe { interfaces__srv__CameraData_Response__Sequence__copy(in_seq, out_seq as *mut _) }
  }
}

impl rosidl_runtime_rs::Message for CameraData_Response {
  type RmwMsg = Self;
  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> { msg_cow }
  fn from_rmw_message(msg: Self::RmwMsg) -> Self { msg }
}

impl rosidl_runtime_rs::RmwMessage for CameraData_Response where Self: Sized {
  const TYPE_NAME: &'static str = "interfaces/srv/CameraData_Response";
  fn get_type_support() -> *const std::ffi::c_void {
    // SAFETY: No preconditions for this function.
    unsafe { rosidl_typesupport_c__get_message_type_support_handle__interfaces__srv__CameraData_Response() }
  }
}






#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_service_type_support_handle__interfaces__srv__HmiSnapshot() -> *const std::ffi::c_void;
}

// Corresponds to interfaces__srv__HmiSnapshot
#[allow(missing_docs, non_camel_case_types)]
pub struct HmiSnapshot;

impl rosidl_runtime_rs::Service for HmiSnapshot {
    type Request = HmiSnapshot_Request;
    type Response = HmiSnapshot_Response;

    fn get_type_support() -> *const std::ffi::c_void {
        // SAFETY: No preconditions for this function.
        unsafe { rosidl_typesupport_c__get_service_type_support_handle__interfaces__srv__HmiSnapshot() }
    }
}




#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_service_type_support_handle__interfaces__srv__HmiCommand() -> *const std::ffi::c_void;
}

// Corresponds to interfaces__srv__HmiCommand
#[allow(missing_docs, non_camel_case_types)]
pub struct HmiCommand;

impl rosidl_runtime_rs::Service for HmiCommand {
    type Request = HmiCommand_Request;
    type Response = HmiCommand_Response;

    fn get_type_support() -> *const std::ffi::c_void {
        // SAFETY: No preconditions for this function.
        unsafe { rosidl_typesupport_c__get_service_type_support_handle__interfaces__srv__HmiCommand() }
    }
}




#[link(name = "interfaces__rosidl_typesupport_c")]
extern "C" {
    fn rosidl_typesupport_c__get_service_type_support_handle__interfaces__srv__CameraData() -> *const std::ffi::c_void;
}

// Corresponds to interfaces__srv__CameraData
#[allow(missing_docs, non_camel_case_types)]
pub struct CameraData;

impl rosidl_runtime_rs::Service for CameraData {
    type Request = CameraData_Request;
    type Response = CameraData_Response;

    fn get_type_support() -> *const std::ffi::c_void {
        // SAFETY: No preconditions for this function.
        unsafe { rosidl_typesupport_c__get_service_type_support_handle__interfaces__srv__CameraData() }
    }
}



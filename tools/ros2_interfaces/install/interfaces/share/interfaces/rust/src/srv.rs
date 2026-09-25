#[cfg(feature = "serde")]
use serde::{Deserialize, Serialize};




// Corresponds to interfaces__srv__HmiSnapshot_Request

// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiSnapshot_Request {

    // This member is not documented.
    #[allow(missing_docs)]
    pub structure_needs_at_least_one_member: u8,

}



impl Default for HmiSnapshot_Request {
  fn default() -> Self {
    <Self as rosidl_runtime_rs::Message>::from_rmw_message(super::srv::rmw::HmiSnapshot_Request::default())
  }
}

impl rosidl_runtime_rs::Message for HmiSnapshot_Request {
  type RmwMsg = super::srv::rmw::HmiSnapshot_Request;

  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> {
    match msg_cow {
      std::borrow::Cow::Owned(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        structure_needs_at_least_one_member: msg.structure_needs_at_least_one_member,
      }),
      std::borrow::Cow::Borrowed(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
      structure_needs_at_least_one_member: msg.structure_needs_at_least_one_member,
      })
    }
  }

  fn from_rmw_message(msg: Self::RmwMsg) -> Self {
    Self {
      structure_needs_at_least_one_member: msg.structure_needs_at_least_one_member,
    }
  }
}


// Corresponds to interfaces__srv__HmiSnapshot_Response

// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiSnapshot_Response {

    // This member is not documented.
    #[allow(missing_docs)]
    pub success: bool,


    // This member is not documented.
    #[allow(missing_docs)]
    pub message: std::string::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub snapshot_json: std::string::String,

}



impl Default for HmiSnapshot_Response {
  fn default() -> Self {
    <Self as rosidl_runtime_rs::Message>::from_rmw_message(super::srv::rmw::HmiSnapshot_Response::default())
  }
}

impl rosidl_runtime_rs::Message for HmiSnapshot_Response {
  type RmwMsg = super::srv::rmw::HmiSnapshot_Response;

  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> {
    match msg_cow {
      std::borrow::Cow::Owned(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        success: msg.success,
        message: msg.message.as_str().into(),
        snapshot_json: msg.snapshot_json.as_str().into(),
      }),
      std::borrow::Cow::Borrowed(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
      success: msg.success,
        message: msg.message.as_str().into(),
        snapshot_json: msg.snapshot_json.as_str().into(),
      })
    }
  }

  fn from_rmw_message(msg: Self::RmwMsg) -> Self {
    Self {
      success: msg.success,
      message: msg.message.to_string(),
      snapshot_json: msg.snapshot_json.to_string(),
    }
  }
}


// Corresponds to interfaces__srv__HmiCommand_Request

// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiCommand_Request {

    // This member is not documented.
    #[allow(missing_docs)]
    pub command: std::string::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub command_id: std::string::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub payload_json: std::string::String,

}



impl Default for HmiCommand_Request {
  fn default() -> Self {
    <Self as rosidl_runtime_rs::Message>::from_rmw_message(super::srv::rmw::HmiCommand_Request::default())
  }
}

impl rosidl_runtime_rs::Message for HmiCommand_Request {
  type RmwMsg = super::srv::rmw::HmiCommand_Request;

  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> {
    match msg_cow {
      std::borrow::Cow::Owned(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        command: msg.command.as_str().into(),
        command_id: msg.command_id.as_str().into(),
        payload_json: msg.payload_json.as_str().into(),
      }),
      std::borrow::Cow::Borrowed(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        command: msg.command.as_str().into(),
        command_id: msg.command_id.as_str().into(),
        payload_json: msg.payload_json.as_str().into(),
      })
    }
  }

  fn from_rmw_message(msg: Self::RmwMsg) -> Self {
    Self {
      command: msg.command.to_string(),
      command_id: msg.command_id.to_string(),
      payload_json: msg.payload_json.to_string(),
    }
  }
}


// Corresponds to interfaces__srv__HmiCommand_Response

// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct HmiCommand_Response {

    // This member is not documented.
    #[allow(missing_docs)]
    pub success: bool,


    // This member is not documented.
    #[allow(missing_docs)]
    pub message: std::string::String,


    // This member is not documented.
    #[allow(missing_docs)]
    pub result_json: std::string::String,

}



impl Default for HmiCommand_Response {
  fn default() -> Self {
    <Self as rosidl_runtime_rs::Message>::from_rmw_message(super::srv::rmw::HmiCommand_Response::default())
  }
}

impl rosidl_runtime_rs::Message for HmiCommand_Response {
  type RmwMsg = super::srv::rmw::HmiCommand_Response;

  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> {
    match msg_cow {
      std::borrow::Cow::Owned(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        success: msg.success,
        message: msg.message.as_str().into(),
        result_json: msg.result_json.as_str().into(),
      }),
      std::borrow::Cow::Borrowed(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
      success: msg.success,
        message: msg.message.as_str().into(),
        result_json: msg.result_json.as_str().into(),
      })
    }
  }

  fn from_rmw_message(msg: Self::RmwMsg) -> Self {
    Self {
      success: msg.success,
      message: msg.message.to_string(),
      result_json: msg.result_json.to_string(),
    }
  }
}


// Corresponds to interfaces__srv__CameraData_Request

// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct CameraData_Request {

    // This member is not documented.
    #[allow(missing_docs)]
    pub camera_id: i32,

}



impl Default for CameraData_Request {
  fn default() -> Self {
    <Self as rosidl_runtime_rs::Message>::from_rmw_message(super::srv::rmw::CameraData_Request::default())
  }
}

impl rosidl_runtime_rs::Message for CameraData_Request {
  type RmwMsg = super::srv::rmw::CameraData_Request;

  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> {
    match msg_cow {
      std::borrow::Cow::Owned(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        camera_id: msg.camera_id,
      }),
      std::borrow::Cow::Borrowed(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
      camera_id: msg.camera_id,
      })
    }
  }

  fn from_rmw_message(msg: Self::RmwMsg) -> Self {
    Self {
      camera_id: msg.camera_id,
    }
  }
}


// Corresponds to interfaces__srv__CameraData_Response

// This struct is not documented.
#[allow(missing_docs)]

#[allow(non_camel_case_types)]
#[cfg_attr(feature = "serde", derive(Deserialize, Serialize))]
#[derive(Clone, Debug, PartialEq, PartialOrd)]
pub struct CameraData_Response {

    // This member is not documented.
    #[allow(missing_docs)]
    pub normal_points: sensor_msgs::msg::PointCloud2,

}



impl Default for CameraData_Response {
  fn default() -> Self {
    <Self as rosidl_runtime_rs::Message>::from_rmw_message(super::srv::rmw::CameraData_Response::default())
  }
}

impl rosidl_runtime_rs::Message for CameraData_Response {
  type RmwMsg = super::srv::rmw::CameraData_Response;

  fn into_rmw_message(msg_cow: std::borrow::Cow<'_, Self>) -> std::borrow::Cow<'_, Self::RmwMsg> {
    match msg_cow {
      std::borrow::Cow::Owned(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        normal_points: sensor_msgs::msg::PointCloud2::into_rmw_message(std::borrow::Cow::Owned(msg.normal_points)).into_owned(),
      }),
      std::borrow::Cow::Borrowed(msg) => std::borrow::Cow::Owned(Self::RmwMsg {
        normal_points: sensor_msgs::msg::PointCloud2::into_rmw_message(std::borrow::Cow::Borrowed(&msg.normal_points)).into_owned(),
      })
    }
  }

  fn from_rmw_message(msg: Self::RmwMsg) -> Self {
    Self {
      normal_points: sensor_msgs::msg::PointCloud2::from_rmw_message(msg.normal_points),
    }
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



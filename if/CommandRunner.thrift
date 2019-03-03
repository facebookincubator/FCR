// Copyright (c) 2017-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree. An additional grant
// of patent rights can be found in the PATENTS file in the same directory.
//

include "common/fb303/if/fb303.thrift"

namespace py.asyncio fbnet.command_runner_asyncio.CommandRunner


exception FBNetDataException {
  1: string message,
}

exception UnsupportedDeviceException {
  1: string message,
}

exception SessionException {
  1: string message,
}

exception UnsupportedCommandException {
  1: string message,
}

exception InstanceOverloaded {
  1: string message,
}

const string CONS_AUTO = 'auto'
const string FAILURE_STATUS = 'failure'
const string SUCCESS_STATUS = 'success'

enum SessionType {
  SSH = 1,
  SSH_NETCONF = 2,
}

struct SessionData {
  // see section 6.5 in RFC: https://tools.ietf.org/html/rfc4254
  // One of the following needs to be specified.

  // We will prefer subsystem over exec_command if both are specified.
  // This uses the SSH subsystem command to start the netconf session
  //
  // session_data = fcr_ttypes.SessionData(subsystem='xmlagent')
  //
  // dev = Device(hostname='rtr-name',
  //              session_type=fcr_ttypes.SessionType.SSH_NETCONF,
  //              session_data=session_data)
  //
  // cmd = '''<?xml version="1.0"?>
  // <nf:rpc xmlns:nf="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:nxos="http://www.cisco.com/nxos:1.0" message-id="110">
  // <nxos:exec-command>
  // <nxos:cmd>show interface brief</nxos:cmd>
  // </nxos:exec-command>
  // </nf:rpc>'''
  //
  // with get_client(FcrClient) as client:
  //     res = client.run(cmd, dev)
  //
  1: optional string subsystem,

  // This command is executed on the remote system to start a session
  //
  // session_data = fcr_ttypes.SessionData(exec_command='netconf format')
  //
  // dev = Device(hostname='rtr-name',
  //              session_type=fcr_ttypes.SessionType.SSH_NETCONF,
  //              session_data=session_data)
  //
  // cmd = '''<?xml version="1.0" ?>
  // <rpc message-id="8566" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  // <get>
  // <filter type="subtree">
  // <optics-oper xmlns="http://cisco.com/ns/yang/Cisco-IOS-XR-controller-optics-oper">
  // <optics-ports>
  // <optics-port>
  // <name>Ots-Och0/2/0/0/1</name>
  // <optics-info />
  // </optics-port>
  // </optics-ports>
  // </optics-oper>
  // </filter>
  // </get>
  // </rpc>'''
  //
  // with get_client(FcrClient) as client:
  //     res = client.run(cmd, dev)

  2: optional string exec_command,
  // Extra options that supported by the given session type. For example,
  //  - The following session support extra_options={'port': PORT}: SSH, NETCONF
  3: optional map<string, string> extra_options,
}

struct Device {
  1: required string hostname,

  10: required string username,
  11: required string password,

  13: optional string console = '',
  // default not using mgmt ip
  14: optional bool mgmt_ip = 0,
  /*
   * explicitly specify the expected prompts for commands. This can be used
   * for commands that don't result in normal prompts (exit, reboot etc)
   *  e.g
   *    prompts = {
   *       'exit': 'login:\s*',   # Expect a login prompt on exit command
   *       'reboot': 'Shutting Down'
   *    }
   *    device = Device(hostname='bb01.iad1', prompts=prompts)
   */
  15: optional map<string, string> command_prompts,

  /*
   * IP address (v4/v6) to be used for the device. If specified, this will be
   * used instead of doing a lookup.
   */
  16: optional string ip_address,

  /*
   * Session Type to use for this device. This overrides the default session
   * type for the device.
   */
  17: optional SessionType session_type,

  /*
   * The optional session data that is needed to initialize the session.
   */
  18: optional SessionData session_data,
}

struct CommandResult {
  1: required string output,
  // if everything works, status = SUCCESS_STATUS
  // if there is some error, status contains the error msg and output has
  // what has received so far
  2: required string status,
  3: required string command,

  // Capabilities for the session.
  // This used to return the initial hello message from the peer.
  // The hello message specifies the server capabilities that clients can
  // use to verify support for data models.
  4: optional string capabilities,
}

struct Session {
  1: required i64 id,
  2: required string name,
  3: required string hostname,
}

service Command extends fb303.FacebookService {
  /* Run a command on a device.
   *
   * A command string is a single command, e.g., 'show version'.
   * A command string could contain multiple commands separated by newlines,
   * e.g., a configlet like
   *
   *    'conf t\nsnmp-server community TEST RO\nexit'
   *
   * @return CommandResult
   */
  CommandResult run(
    1: string command
    2: Device device

    /*
     * optional arguments
     */
    // max time (sec) to wait to get the full response
    3: i32 timeout = 300
    // max time (sec) allowed to spend authenticating into the device
    4: i32 open_timeout = 30

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  ) throws (1: SessionException se, 2: UnsupportedDeviceException ude)

  /* Run a list of commands on a list of devices.
   *
   * All commands to each device are run serially within a single session
   * in the specified order. If a command in a list fails to execute,
   * subsequent commands to the device are skipped. A command string could be a
   * single command or a configlet, see comments for run() for examples.
   *
   * @return Mapping from hostname to CommandResult
   */
  map<string, list<CommandResult>> bulk_run(
    1: map<Device, list<string>> device_to_commands

    /*
     * optional arguments
     */
    // max time (sec) to wait to get the full response of a single command.
    // the max time it could take per device is timeout * number of commands
    3: i32 timeout = 300
    // max time (sec) allowed to spend authenticating into the device
    4: i32 open_timeout = 30

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  )

   /*
    * To USER: DO NOT use this function
    *
    * To Developer: This is another version of bulk_run which
    * does not split big request into smaller one
    *
    */
  map<string, list<CommandResult>> bulk_run_local(
    1: map<Device, list<string>> device_to_commands
    3: i32 timeout = 300
    4: i32 open_timeout = 30

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
   ) throws (1: InstanceOverloaded ioe)

  /*
   * The following APIs is used to interact with a single device just
   * as if you are accessing the device CLI.
   *
   * IMPORTANT:
   * 1. You MUST use the same thrift connection to open and run
   *    commands on a session. Sessions opened by one thrift connection aren't
   *    valid for running commands via another thrift connection.
   * 2. Remember to close the session after use to prevent any stale connection
   *    to the device.
   *
   * Example:
   *   session = fcr_client.open_session(device)
   *   fcr_client.run_session(session, 'show version')
   *   // push a configlet
   *   configlet = '''conf t
snmp-server community TEST RO
exit
wr mem'''
   *   fcr_client.run_session(session, configlet)
   *   fcr_client.run_session(session, 'show run | include snmp-server')
   *   fcr_client.close_session(session)
   *
   */


  /* Establish a management session with a device. The session does not persist
   * across thrift connections, i.e., the session dies when you are disconnected
   * from the command runner thrift service.
   *
   * @return Session
   */
  Session open_session(
    1: Device device

    /*
     * optional arguments
     */
    // max time (sec) allowed to spend authenticating into the device
    2: i32 open_timeout = 60
    // max time (sec) allowed for the session to go unused
    3: i32 idle_timeout = 300

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  ) throws (1: SessionException se)

  /* Run a command within a session. The command could potentially modify
   * the device configuration based on the permission you have on the device.
   * The command could be multi-line (separated by \n'), e.g.,
   * command = """
conf t
?
"""
   *
   * @return CommandResult
   */
  CommandResult run_session(
    1: Session session
    2: string command

    /*
     * optional arguments
     */
    // max time (sec) to wait to get the full response
    3: i32 timeout = 300

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  ) throws (1: SessionException se)

  /* Close the session. Each open_session call should be accompanied with a
   * close_session call to free connection with the device.
   *
   * @return void
   */
  void close_session(
    1: Session session

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  ) throws (1: SessionException se)

  // open_raw_session() should be used when user want to bypass session setup
  // (login and run setup commands).
  // If open_raw_session(), following calls should be run_raw_session() and
  // close_raw_session().
  Session open_raw_session(
    1: Device device

    /*
     * optional arguments
     */
    // max time (sec) allowed to spend authenticating into the device
    2: i32 open_timeout = 60
    // max time (sec) allowed for the session to go unused
    3: i32 idle_timeout = 300

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  ) throws (1: SessionException se)


  /*
   * This is similar to run_session(). This is used in conjunction with
   * open_raw_session. The user needs to explicitly specify the expected
   * prompt_regex.
   *
   * @return CommandResult
   */
  CommandResult run_raw_session(
    1: Session session
    2: string command

    /*
     * optional arguments
     */
    // max time (sec) to wait to get the full response
    3: i32 timeout = 300

    // Specify a prompt that you expect at the end of command.
    4: string prompt_regex

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  ) throws (1: SessionException se)

  /* Close the session. Each open_raw_session call should be accompanied with a
   * close_session call to free connection with the device.
   *
   * @return void
   */
  void close_raw_session(
    1: Session session

    /*
     * don't populate the following arguments unless you know what you are doing
     */
    10: string client_ip = ""
    11: string client_port = ""
    12: string uuid = ""
  ) throws (1: SessionException se)
}

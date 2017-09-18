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
}

struct CommandResult {
  1: required string output,
  // if everything works, status = SUCCESS_STATUS
  // if there is some error, status contains the error msg and output has
  // what has received so far
  2: required string status,
  3: required string command,
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
  ) throws (1: SessionException se)
}

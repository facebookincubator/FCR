# FBNet Command Runner (FCR)

A thrift service to run commands on heterogeneous Network devices with configurable parameters.
It scales to a large number of devices.

It hides most of the devices specific details like:

* Prompt processing
* IP Address lookup
* The base implementation only supports SSH. But other type of connections can be easily added.
* Client can use any language of choice, to communicate with server using thrift call.

## Requirements

* python3.5+
* asyncssh

## Installing FCR

FCR can be quickly installed using `pip`. Just clone the git repo and install using the given requirement files

```bash
# Clone the git repo.
git clone --recursive https://github.com/facebookincubator/FCR.git

# Create a virtual environment
python3 -m venv venv
. venv/bin/activate

cd FCR
# use pip to install the required modules.
pip3 install -r requirements.txt
pip3 install .
```

## FCR client


```python
import asyncio

from fbnet.command_runner.thrift_client import AsyncioThriftClient

# Import FCR Thrift Types
from fbnet.command_runner_asyncio.CommandRunner import ttypes as fcr_ttypes

# Import FCR Service Client
from fbnet.command_runner_asyncio.CommandRunner.Command import Client as FcrClient
```

### get the device and user information


```python
import getpass

# Device Information
hostname = 'dev-001'
username = 'netbot'
password = getpass.getpass('%s Password: ' % username)
```

    netbot Password: ········


### run

Run a commands on a single device. Multiple commands are separated by new lines.

* see [run api definition](if/CommandRunner.thrift#L80-L97)
* return: [struct CommandResult](if/CommandRunner.thrift#L54-L61)

```python
# Destination device
device = fcr_ttypes.Device(hostname=hostname, username=username, password=password)

async def run(cmd, device):
    async with AsyncioThriftClient(FcrClient, 'localhost', 5000) as client:
        res = await client.run(cmd, device)
        # type of res is `struct CommandResult`
        print(res.output)

loop = asyncio.get_event_loop()
loop.run_until_complete(run('uname -a\nip -4 add list eth0', device))
```

    netbot@dev-001:~$ uname -a
    Linux dev-001 4.4.0-79-generic #100-Ubuntu SMP Wed May 17 19:58:14 UTC 2017 x86_64 GNU/Linux
    netbot@dev-001:~$ ip -4 add list eth0
    161: eth0@if162: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
        inet 172.17.0.2/16 scope global eth0
           valid_lft forever preferred_lft forever


### bulk_run

Multiple commands can be run on multiple devices using `bulk_run` api.

* see [bulk_run api definition](if/CommandRunner.thrift#L108-L125)
* return: map<device_name, list<[struct CommandResult](if/CommandRunner.thrift#L54-L61)>>


```python
devices = [
    fcr_ttypes.Device(hostname='dev-%03d' % i, username=username, password=password)
    for i in range(1, 150)
]

dev_cmds = {dev: ['uname -r', 'whoami'] for dev in devices}

async def bulk_run(dev_cmds):
    async with AsyncioThriftClient(FcrClient, 'localhost', 5000) as client:
        results = await client.bulk_run(dev_cmds)
        # result is a map<devname, list<CommandResult>>
        return results

loop = asyncio.get_event_loop()
results = loop.run_until_complete(bulk_run(dev_cmds))

print("Some results from the devices")
for dev in devices[::10]:
    hostname = dev.hostname
    print(hostname, ':', results[hostname][0].output.splitlines()[1:])
```

    Some results from the devices
    dev-001 : ['4.4.0-79-generic']
    dev-011 : ['4.4.0-79-generic']
    dev-021 : ['4.4.0-79-generic']
    dev-031 : ['4.4.0-79-generic']
    dev-041 : ['4.4.0-79-generic']
    dev-051 : ['4.4.0-79-generic']
    dev-061 : ['4.4.0-79-generic']
    dev-071 : ['4.4.0-79-generic']
    dev-081 : ['4.4.0-79-generic']
    dev-091 : ['4.4.0-79-generic']
    dev-101 : ['4.4.0-79-generic']
    dev-111 : ['4.4.0-79-generic']
    dev-121 : ['4.4.0-79-generic']
    dev-131 : ['4.4.0-79-generic']
    dev-141 : ['4.4.0-79-generic']


### Persisting connection to the device

Sometimes you want to keep the connection to the device open across multiple commands. For this FCR provides following APIS

* **[open_session](if/CommandRunner.thrift#L178-L194)** : open a connection to the device.
* **[run_session](if/CommandRunner.thrift#L206-L221)** : run a command using the previously opened connection.
* **[close_session](if/CommandRunner.thrift#L228-L236)** : close the connection to the device.



```python
# Destination device
device = fcr_ttypes.Device(hostname='dev-001', username=username, password=password)

async def fcr_session():

    async with AsyncioThriftClient(FcrClient, 'localhost', 5000) as client:
        # Open a session to the device
        session = await client.open_session(device)

        # Run commands on the open session
        res = await client.run_session(session, 'uname -a')
        print(res.output)

        res = await client.run_session(session, 'ip addr show | grep "inet\>"')
        print(res.output)

        # Finally Close the session
        await client.close_session(session)

loop = asyncio.get_event_loop()
results = loop.run_until_complete(fcr_session())
```

    netbot@dev-001:~$ uname -a
    Linux dev-001 4.4.0-79-generic #100-Ubuntu SMP Wed May 17 19:58:14 UTC 2017 x86_64 GNU/Linux
    netbot@dev-001:~$ ip addr show | grep "inet\>"
        inet 127.0.0.1/8 scope host lo
        inet 172.17.0.2/16 scope global eth0


## Customize FCR service

FCR is a thrift service that provides APIs to run remote commands on devices. To use FCR service you will need to extend the FcrServiceBase to adapt it to your specific environment. FCR provides interfaces to configure supported vendors and allows you to extend it get device information for your backend database.


```python
from fbnet.command_runner.service import FcrServiceBase

class FCRService(FcrServiceBase):

    def __init__(self, args=None):
        super().__init__("FCR", args=args)

def main(args=None):
    service = FCRService()
    service.start(args)
```

You will need to customize the service to adapt to your specific environment.  This will mostly work out of the box, but to use it effectively you will need to adapt it according to your specific environment

You will need to customize FCR service to work with your environment.

* Device Vendor information: Information about vendors whose devices are in your Network. e.g. vendor name, device prompts. See below for more details.
* Device Database: for loading metadata from your data source, e.g. names of devices, device address, device vendors.

### Device Vendors

For FCR to work, it needs to know the prompts (regex) to expect from the devices. Each vendor can have a different set of prompts


* **setup commands**: A set of initial commands to setup the connections. These commands are sent to the device everytime a new session is created. e.g. [`term len 0`,`term width 511`].
* **prompt regex**: A list of expected prompts (regex) from devices of this vendor.  
* **command timeouts**: A default timeout specific to this vendor. This allows us to work with slow vendors
* **clear command**: Command used to clear the last command. A sequence used to clear the command line. (Default: ^U)
* **session type**: Session type to be used for the vendor. Most of the vendors will support the SSHCommandSession. Some vendor may provide a programmable interface, which may require a custom session type

This information can be provided to FCR service in json file. This file can be specified using '--device-vendors' command line options.

#### device_vendors.json
```json
{
  "vendor_config": {
    "vendor1": {
        "vendor_name": "vendor1",
        "session_type": "ssh",
        "prompt_regex": ["[\\w.]+#\\s*"],
        "cli_setup": [
          "en",
          "term len 0"
        ],
        "shell_prompts": ["\\$"]
    },
    "vendor2": {
        "vendor_name": "vendor2",
        "session_type": "ssh",
        "prompt_regex": ["[\\w./:]+[$#]\\s*"],
        "cli_setup": [ "term len 0" ]
    },
  }

```

### Device DB

FCR relies in a devices database to resolve device information. This database is populated with `device_info` objects. You will need to extend this database and implement `_fetch_device_data()` method

`_fetch_device_data()` needs to return an array of `fbnet.command_runner.device_info` objects. if needed you can extend `fbnet.command_runner.device_info` according to your specific environment.


```python
from fbnet.command_runner.device_db import BaseDeviceDB
from fbnet.command_runner.options import Option

# You will likely get this data from your backend systems.
# But for illustration we will assume this is available in JSON
# format
import json
json_devdata = '''
[
  {"host": "rtr1", "chassis": "T1000", "ip": ["10.0.0.1","20.0.0.1"], "role": "router", "vendor": "vendor1"},
  {"host": "rtr2", "chassis": "T5000", "ip": ["10.0.0.2","20.0.0.2"], "role": "router", "vendor": "vendor2"},
  {"host": "rtr3", "chassis": "T2000", "ip": ["10.0.0.3","20.0.0.3"], "role": "switch", "vendor": "vendor2"}
]
'''

class DeviceDB(BaseDeviceDB):

    async def _fetch_device_data(self, name_filter=None):
        '''
        Fetch data from your backend database.

        This sample implementation assumes you have the data in a json format
        '''        
        devinfos = json.loads(json_devdata)

        return {self._make_dev(devinfo) for devinfo in devinfos }

    def _make_dev(devinfo):
        return DeviceInfo(
            self.service,
            hostname=devinfo['host'],
            username='default',     # typically a user with a bare minimum RO privileges
            password='passwd',
            pref_ips=devinfo['ip'], # a list of IP addresses in order of preferences
            ip=devinfo['ip'][0],    # the default fallback IP (after exhausting the pref_ips
            vendor_data=self.app.vendors.get(devinfo['vendor']),
            role=devinfo['role'],
            ch_model=devinfo['ch_model'])
```

## CLI options for the server

```sh
bin/fcr_service.py --help
```

    usage: fcr_service.py [-h] [--remote_call_overhead REMOTE_CALL_OVERHEAD]
                          [--lb_threshold LB_THRESHOLD] [-p PORT]
                          [--asyncio_debug]
                          [--log_level {debug,info,warning,error,critical}]
                          [--max_default_executor_threads MAX_DEFAULT_EXECUTOR_THREADS]
                          [--exit_max_wait EXIT_MAX_WAIT]
                          [--device_db_update_interval DEVICE_DB_UPDATE_INTERVAL]
                          [--device_name_filter DEVICE_NAME_FILTER]

    A thrift service to run commands on heterogeneous Network devices with configurable parameters.

    It hides most of the devices specific details:

    * Prompt processing
    * IP Address lookup
    * Session Types

    The clients can be implemented in any language supported by thrift

    optional arguments:
      --asyncio_debug       turn on debug for asyncio (default: False)
      --device_db_update_interval DEVICE_DB_UPDATE_INTERVAL
                            device db update interval (in seconds). (default:
                            1800)
      --device_name_filter DEVICE_NAME_FILTER
                            A regex to restrict the database to matching device
                            names. This is passed as an argument to
                            self._fetch_devices_data() method. (default: None)
      --exit_max_wait EXIT_MAX_WAIT
                            Max time (seconds) to wait for session to terminate.
                            This allows existing session to complete gracefully.
                            (default: 300)
      --lb_threshold LB_THRESHOLD
                            Load Balance threashold for bulk_run calls. If number
                            of devices is greater than this threashold, the
                            requests are broken and send to other instances using
                            bulk_run_local() api (default: 100)
      --log_level {debug,info,warning,error,critical}
                            logging level (default: info)
      --max_default_executor_threads MAX_DEFAULT_EXECUTOR_THREADS
                            Max number of worker threads. These are used for
                            long running blocking non-async calls that are not
                            handled in async loop. The default should be good
                            enough for most use cases (default: 4)
      --remote_call_overhead REMOTE_CALL_OVERHEAD
                            Overhead for running commands remotely (for bulk
                            calls). This is subtracted from the requested timeout
                            when request are forwarded to remote service. This
                            allows the bulk_run() to completed within the
                            requested timeout (default: 20)
      -h, --help            show this help message and exit
      -p PORT, --port PORT  TCP port for FCR service (default: 5000)


## License

FBNet Command Runner is MIT-licensed.

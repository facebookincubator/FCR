
# Using FCR with docker containers

Here we demonstrate the use of FCR in a simple setup. The setup simulates devices as a bunch of **docker** containers.

We will also be using the docker service to get the list of devices to update our device database.

## Setup
### Docker container

We have a bare minumum container running a ssh service (see host/Dockerfile). We have added a test user(`netbot`) that we will use to login into the devices.

#### Startup


```bash
%%bash

NUM_DEVICES=3

IMAGENAME='fcr-host-device'

docker build -t ${IMAGENAME} device

# Spawn a set of containers
DEVICES=$(printf "dev-%03d " $(seq 1 $NUM_DEVICES))

for dev in ${DEVICES}; do
    docker run -h "${dev}" --name "${dev}" -d ${IMAGENAME}
done
```

    
    Step 1/8 : FROM debian:latest
     ---> a25c1eed1c6f
    Step 2/8 : RUN apt-get update &&        apt-get install -y openssh-server &&        mkdir /var/run/sshd
     ---> Using cache
     ---> a41795fb44c3
    Step 3/8 : RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd
     ---> Using cache
     ---> 3fc11a21f8e7
    Step 4/8 : RUN echo "set show-all-if-ambiguous on" >> /etc/inputrc
     ---> Using cache
     ---> fce13fbe0bb4
    Step 5/8 : RUN adduser --disabled-password --gecos '' netbot         && echo 'netbot:bot1234' | chpasswd
     ---> Using cache
     ---> 2fc985369757
    Step 6/8 : EXPOSE 22
     ---> Using cache
     ---> 30388be4464f
    Step 7/8 : ADD startup.sh /usr/local/bin
     ---> Using cache
     ---> 13847ee805e1
    Step 8/8 : CMD /usr/local/bin/startup.sh
     ---> Using cache
     ---> 3678d8e280d3
    Successfully built 3678d8e280d3
    177eed923d0c737e9ef6546fd8c20f66e8cab99404ee4b08174e892959e3f12f
    c8063dd77537c348f47f1ac99bd940179c58807f0248437700c358fab78b306d
    09fb09448d795a5d7a1f4d9efcab053ba7c7a85a1d8dc847782369a2efb0044b


#### Shutdowns

Once you are done, you can cleanup the containers


```bash
%%bash

containers=$(docker ps --filter=ancestor=fcr-host-device -aq)
echo "Stoping containers"
docker stop ${containers}
echo "Removing stopped containers"
docker rm ${containers}
```

    Stoping containers
    5a69417060b3
    8fe9cf662638
    c56625e6aae9
    Removing stopped containers
    5a69417060b3
    8fe9cf662638
    c56625e6aae9


### FCR Service

The FCR service will be extended to add support for docker apis. The docker APIs will be used to get a list of running containers. We will also get the container API information using docker APIs

We will also provide a custom `device_vendors.json` file. This file will used to specify properties of ``docker`` vendor.

#### device_vendors.json

```json
{
    "vendor_config": {
        "docker": {
            "vendor_name": "docker",
                "session_type": "ssh",
                "prompt_regex": ["[\\w]+@[\\w.-]+:[/\\w~]+[#$]\\s*"],
                "cli_setup": ["bind '?':complete"]
        }
    }
}
```

#### DeviceDB

* Adapt the `BaseDeviceDB` to get device information using docker APIs.


```python
import docker

from fbnet.command_runner.device_db import BaseDeviceDB
from fbnet.command_runner.device_info import DeviceInfo, DeviceIP

class DeviceDB(BaseDeviceDB):

    docker_client = docker.from_env()

    async def _fetch_device_data(self, name_filter=None):
        self.logger.info('fetch_device_data: %s', name_filter)

        containers = await self._run_in_executor(self.list_containers)

        return [self.create_device(c) for c in containers]

    @classmethod
    def list_containers(cls):
        return cls.docker_client.containers.list()

    def create_device(self, container):
        vendor = 'docker'
        ip = container.attrs['NetworkSettings']['IPAddress']
        addr = DeviceIP('addr', ip, False)
        return DeviceInfo(
                self.service,
                container.name,
                'netbot', 'bot1234',
                [addr], addr,
                self.service.vendors.get(vendor),
                'Demo', 'Ubuntu')
```

For complete implementation see [fcr_service.py](fcr_service.py)


```bash
%%bash
./fcr_service.py
```

    INFO:fcr.DeviceVendors:loading local file
    INFO:fcr.DeviceVendors:loading vendor: docker
    INFO:fcr.DeviceDB:fetch_device_data: None
    INFO:fcr.DeviceDB:Waiting for data
    INFO:fcr.DeviceDB:Device data valid
    INFO:FCR:Registering Counter manager
    INFO:fcr.CommandServer:server started: 5000 
    INFO:fcr.SSHCommandSession.docker.dev-001:140122665405240: Created key=(140122665405240, '', '')
    INFO:fcr.SSHCommandSession.docker.dev-001:140122665405240: Connecting to: 172.17.0.2: 22
    INFO:fcr.SSHCommandSession.docker.dev-001:140122665405240: Connected: {'sockname': ('172.17.0.1', 59032), 'fd': 13}
    INFO:fcr.SSHCommandSession.docker.dev-001:140122665405240: RUN: b"bind '?':complete\n"
    INFO:fcr.SSHCommandSession.docker.dev-001:140122665405240: RUN: b'uname -a\n'
    INFO:FCR:Stopping: CommandServer
    INFO:FCR:Stopping: DeviceDB
    INFO:fcr.CommandServer:closing the server
    INFO:FCR:Shutdown: no pending sesison
    INFO:FCR:Terminating



```python

```

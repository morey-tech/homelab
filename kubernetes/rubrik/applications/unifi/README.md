# unifi
Due to the `unifi` controller service running on a separate layer 3 network from the devices (under metallb), they will be picked up automatically. To connect a device to the controller, ssh into it and run (credentials for provisioned devices are `root - server` in Bitwarden):

```
ssh root@192.168.1.20

set-inform http://10.8.0.4:8080/inform
```
Note: it may take 2-3 tries before the device is picked up.
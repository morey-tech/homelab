# CPU Whisper runtime

This derives from the multi-architecture Speaches 0.8.3 CPU image and changes only
`/home/ubuntu` traversal permissions. Its prebuilt Python, PyAV and faster-whisper
libraries otherwise cannot run with OpenShift's assigned UID. No GPU runtime is
added, and the application explicitly selects CPU/int8 inference.

```bash
podman build -f containers/whisper-cpu/Containerfile -t homelab-whisper-cpu containers/whisper-cpu
```

The standard container workflow publishes amd64 and arm64 images after the human
pushes this reviewed commit. Record the resulting multi-platform registry digest
in the follow-up speech deployment before enabling it in the inference-server
Kustomization. A local build digest is not a substitute for the published CI digest.

The HTTP wrapper and its tests are part of the separate application change under
`kubernetes/ocp-mgmt/applications/whisper-cpu`; this prerequisite commit publishes
only the runtime image.

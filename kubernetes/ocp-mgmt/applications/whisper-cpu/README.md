# CPU Whisper through MaaS

This backend adds `POST /inference-server/local-llm/v1/audio/transcriptions` behind the existing [MaaS gateway](https://maas.apps.ocp-mgmt.rh-lab.morey.tech). It accepts OpenAI multipart transcription requests with `model=whisper-1` and `response_format=json` or `text`.

The inference-server Kustomization includes this backend. Its [CPU runtime image](../../../../containers/whisper-cpu/README.md) was published by [build 40106274364](https://github.com/morey-tech/homelab/actions/runs/40106274364) from commit `85189c5`; the Deployment pins the published multi-platform digest `sha256:371dc00985a6d9bb312313c6dafae4087f52741126f5860fdea032174bc1d0e3`. Review and commit the backend and MaaS multipart filter together, then push and wait for both Applications to reconcile before testing voice requests.

## Runtime and limits

The image derives from pinned Speaches 0.8.3 CPU dependencies and fixes its Python parent-directory permissions for arbitrary OpenShift UIDs. A small stdlib HTTP wrapper invokes faster-whisper with `device=cpu`, int8, two CPU threads, and one inference worker. The pod is restricted to the ordinary ms-02/ms-04 nodes and requests no GPU or GPU runtime. Shared Qwen configuration is unchanged.

| Setting | Value |
|---|---|
| Model | `WHISPER_MODEL=Systran/faster-whisper-base.en` |
| Persistent cache | 5 GiB NVMe PVC, `/cache/models` |
| CPU / memory | request 1 CPU / 1 GiB; limit 2 CPU / 3 GiB |
| Concurrent inference | 1; additional requests receive HTTP 429 |
| Multipart request size | 16 MiB; Hermes limits its audio file to 15 MiB |
| Decoded duration | 5 minutes |
| Upload socket timeout | 20 seconds |
| Inference deadline | 120 seconds; timed-out child is killed and replaced |
| MaaS route timeout | 150 seconds; upstream backend 145 seconds |
| Hermes request timeout | 140 seconds, no automatic client retry |
| Request quota | 6 requests/minute per MaaS identity |

PyAV decodes Signal voice audio to mono 16 kHz samples. Local CPU tests transcribed the public Whisper JFK fixture as FLAC, Ogg/Opus, and M4A/AAC. Audio over five minutes was rejected. The readiness endpoint stays false while the model downloads; a dead inference child fails liveness. A separate writable shared-memory volume supports multiprocessing with a read-only root. Downloads require HTTPS access to Hugging Face and its model CDN. No hosted STT fallback exists.

To change the model, edit `WHISPER_MODEL` in the Deployment and review/commit/push it. For multilingual notes, choose a multilingual faster-whisper model and recheck memory, disk use, and latency. Keep the public request model `whisper-1`; clients cannot select arbitrary models or download locations. Existing cached models remain until deliberately removed through an approved maintenance procedure.

## MaaS integration

The deployed MaaS external-model interface supports chat formats, not a speech-provider registration. This endpoint therefore uses a dedicated Gateway API HTTPRoute under the existing `inference-server/local-llm` entitlement. The gateway's inherited AuthPolicy checks credentials, subscription/model access, and spoofed client identity headers. All subscribers authorized for `local-llm` can use this speech capability; it is not a separate subscription/model identity.

The route-level TokenRateLimitPolicy overrides the gateway's default-deny token policy. Speech responses do not report chat token usage, so the separate request RateLimitPolicy and backend concurrency limit bound audio work. The narrow `whisper-multipart` EnvoyFilter disables only the chat JSON payload processors for `inference-server.whisper-cpu.0`; authentication and rate-limit filters remain enabled. Direct backend traffic is restricted to the MaaS gateway pods by NetworkPolicy.

This routing still needs live verification after GitOps deployment: confirm the generated Envoy route name, inherited auth policy, both rate-limit policies, multipart handling, and subscription denial. Do not describe CPU-only local tests as proof that the MaaS route already works.

```bash
kustomize build kubernetes/ocp-mgmt/applications/whisper-cpu > /tmp/whisper-rendered.yaml
python3 -B -m unittest discover -s kubernetes/ocp-mgmt/applications/whisper-cpu -p 'test_*.py'
# After reviewed GitOps deployment:
oc get deployment,pvc,pods,httproute,tokenratelimitpolicy,ratelimitpolicy -n inference-server
oc get envoyfilter whisper-multipart -n openshift-ingress
oc logs deployment/whisper-cpu -n inference-server --tail=30
```

Use the [integration runbook](../hermes/PERSONAL-NOTES.md) for the authenticated voice test and failure cases. Model cache loss only causes a download; it does not lose notes. The service never persists uploaded recordings beyond a request's temporary file.

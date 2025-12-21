# Intel GPU Setup on OpenShift

This folder configures Intel GPU support using the Intel Device Plugins for Kubernetes with Node Feature Discovery (NFD).

## Architecture Decision: Kustomize vs Intel Operator

**Decision**: Use kustomize-based deployment instead of Intel Device Plugins Operator.

### Comparison

| Aspect | Kustomize (Current) | Intel Operator |
|--------|---------------------|----------------|
| Version | v0.31.1 | v0.32.1 |
| Channel | N/A (direct deployment) | Alpha |
| Stability | Stable, tested | Alpha channel, less mature |
| Complexity | Simple, declarative | Additional CRDs, operator overhead |
| GPU Sharing | Configured via args | Configured via CR |
| Monitoring | Manual ServiceMonitor | Built-in option |
| Updates | Manual version bump | Operator-managed |

### Why Not the Operator?

1. **Alpha Channel**: The Intel Device Plugins Operator is only available in the Alpha channel on OperatorHub, indicating it's not yet production-ready for OpenShift.

2. **No Functional Advantage**: Both approaches provide the same capabilities:
   - GPU device plugin (gpu.intel.com/i915)
   - Monitoring resource (gpu.intel.com/i915_monitoring)
   - GPU sharing (sharedDevNum)
   - Node Feature Rules for GPU detection

3. **Simpler GitOps**: Kustomize deployment is fully declarative and easier to manage via GitOps without operator lifecycle concerns.

4. **Current Setup Works**: The existing configuration is stable and provides all required functionality.

## Components

### From Intel Device Plugins (v0.31.1)

- **NodeFeatureRules**: Detects Intel GPUs and labels nodes with `intel.feature.node.kubernetes.io/gpu=true`
- **GPU Plugin DaemonSet**: Exposes `gpu.intel.com/i915` and `gpu.intel.com/i915_monitoring` resources

### Local Manifests

- **intel-gpu-plugin-rbac.yaml**: ServiceAccount and privileged SCC binding for GPU plugin DaemonSet
- **intel-gpu-exporter.yaml**: Prometheus metrics exporter for GPU utilization
- **intel-gpu-exporter-servicemonitor.yaml**: ServiceMonitor for Prometheus scraping

## GPU Resources

| Resource | Purpose | Exclusive |
|----------|---------|-----------|
| `gpu.intel.com/i915` | GPU compute allocation | Yes (shared via sharedDevNum) |
| `gpu.intel.com/i915_monitoring` | Read-only monitoring access | No |

### GPU Sharing

Configured to allow 5 containers per GPU via `-shared-dev-num 5` argument patch. This enables multiple workloads (e.g., Immich server + ML) to share the single iGPU.

## Metrics

The intel-gpu-exporter exposes metrics with `igpu_` prefix:

```promql
# Power consumption
igpu_power_package        # Total CPU+GPU package watts
igpu_power_gpu            # GPU-only watts

# Utilization
igpu_engines_render_3d_0_busy    # 3D/Compute (OpenVINO)
igpu_engines_video_0_busy        # QuickSync transcoding
igpu_engines_video_1_busy        # QuickSync transcoding (secondary)
igpu_engines_blitter_0_busy      # Copy operations

# Power state
igpu_rc6                  # Power saving % (100% = fully idle)

# Frequency
igpu_frequency_actual     # Current GPU frequency MHz
igpu_frequency_requested  # Requested GPU frequency MHz
```

## SCC Requirements

| Component | Privileged SCC | Reason |
|-----------|----------------|--------|
| intel-gpu-plugin | Yes | hostPath /dev/dri, device plugin socket |
| intel-gpu-exporter | Yes | hostPID, perf counters, /dev/dri |
| Workloads (Immich, etc.) | No | Device plugin handles GPU allocation |

Workloads using `gpu.intel.com/i915` do NOT require privileged SCC - the Intel device plugin handles GPU device mounting via the Kubernetes device plugin framework.

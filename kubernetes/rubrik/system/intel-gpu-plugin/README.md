# intel-gpu-plugin
Add feature labels to nodes if they contain an Intel GPU to aid in the scheduling of pods. Useful for services that benefit from specific GPU features like Intel QuickSync.

Status: Disabled. The iGPU from the host CPU is not passed through to the VM so it can't detect the i915 GPU and label the node. Once the cluster is moved to bare metal, it can be redeploy and tested again.
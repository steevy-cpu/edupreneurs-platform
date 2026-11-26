# Runpod GPU experiment kit (not run)

Nothing in this folder has been executed. No pod, endpoint or GPU was created
for Jude-02A. The specification is in
[`docs/jude-02a/05-runpod-experiment.md`](../../../docs/jude-02a/05-runpod-experiment.md).

| File | What it is |
|---|---|
| `vllm-serve.sh` | The exact serving command for a dedicated pod |
| `worker-vllm.env.example` | Variable names for Runpod's serverless vLLM worker (no values) |
| `experiment-matrix.json` | Which model, weights and GPU each run uses, and why |
| `loadtest.py` | Concurrency ramp with real Jude prompts; refuses to start unless authorised |

**Secrets:** the endpoint URL and key are read from `JUDE_GPU_ENDPOINT_URL` and
`JUDE_GPU_ENDPOINT_KEY`. Do not put them in any file here.

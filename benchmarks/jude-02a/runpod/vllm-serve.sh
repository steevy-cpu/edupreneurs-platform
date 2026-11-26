#!/usr/bin/env bash
# Jude-02A — how the candidate model is to be served for the GPU experiment.
#
# NOT RUN during Jude-02A. This is the specification of the command, kept as a
# script so the experiment is reproducible. Flag names were read from the vLLM
# documentation on 2026-11-26 (stable release then: v0.34.0); re-check them
# against the version you actually pull:  https://docs.vllm.ai/en/stable/cli/serve/
#
# Required environment (set in the pod, never in git):
#   MODEL_ID        Hugging Face repo id, e.g. mistralai/Ministral-3-14B-Instruct-2512
#   VLLM_API_KEY    a long random secret generated for this experiment only
# Optional:
#   HF_TOKEN        only if the model is gated
#   QUANTIZATION    only for formats vLLM does not detect from the weights
set -euo pipefail

: "${MODEL_ID:?set MODEL_ID}"
: "${VLLM_API_KEY:?set VLLM_API_KEY (generate one: openssl rand -hex 32)}"

args=(
  "$MODEL_ID"
  --served-model-name jude-candidate   # the name the benchmark sends; hides the real id
  --host 0.0.0.0 --port 8000
  --api-key "$VLLM_API_KEY"            # see README: this does NOT protect every route
  --max-model-len "${MAX_MODEL_LEN:-4096}"          # Jude: ~1.6k in (conservative) + 500 out
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.90}"
  --max-num-seqs "${MAX_NUM_SEQS:-32}"              # upper bound on batched sequences
  --enable-prefix-caching                           # Jude's system prompt is identical per intent
  --disable-log-requests                            # never log prompts: they hold students' words
)
if [[ -n "${QUANTIZATION:-}" ]]; then
  args+=(--quantization "$QUANTIZATION")
fi

exec vllm serve "${args[@]}"

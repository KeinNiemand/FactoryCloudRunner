# syntax=docker/dockerfile:1.19
ARG BASE_IMAGE=python:3.12-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b
FROM ${BASE_IMAGE}

ENV PIP_ROOT_USER_ACTION=ignore \
    CUDA_HOME=/usr/local/lib/python3.12/site-packages/nvidia/cu13 \
    PATH=/usr/local/lib/python3.12/site-packages/nvidia/cu13/bin:${PATH}

RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gcc \
        libc6-dev \
        libgomp1 \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel hatchling \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cu130 \
        "torch==2.9.0+cu130" \
        "torchvision==0.24.0+cu130" \
        "torchaudio==2.9.0+cu130"

RUN python -m pip install --no-cache-dir \
        "transformers==5.5.0" \
        "datasets==3.6.0" \
        "accelerate==1.11.0" \
        "peft==0.18.1" \
        "trl==0.24.0" \
        "torchdata==0.11.0" \
        "liger-kernel==0.8.0" \
        "bitsandbytes==0.49.2" \
        "deepspeed==0.19.1" \
        "wandb==0.27.0" \
        "diffusers==0.38.0" \
        "sentencepiece==0.2.1" \
        "tyro==0.8.14" \
        "nest-asyncio==1.6.0" \
        "einops==0.8.2" \
        "numpy==2.4.4" \
        "pandas==2.3.3" \
        "scipy==1.18.0" \
        "matplotlib==3.11.0" \
        "tiktoken==0.13.0" \
        "hf-transfer==0.1.9" \
        "safetensors==0.8.0" \
        "fire==0.7.1" \
        "omegaconf==2.3.1" \
        "protobuf==7.35.1" \
        "pydantic==2.12.3" \
        "PyYAML==6.0.3" \
        "ninja==1.13.0" \
        "packaging==26.2" \
        "psutil==7.2.2"

RUN python -m pip install --no-cache-dir --no-deps \
        "nvidia-cuda-nvcc==13.0.88" \
        "torchao==0.14.1" \
        "cut-cross-entropy==25.1.1" \
        "msgspec==0.21.1" \
        "unsloth_zoo==2026.5.1" \
        "unsloth==2026.5.2" \
    && python -m pip install --no-cache-dir --no-deps \
        --index-url https://download.pytorch.org/whl/cu130 \
        "xformers==0.0.33.post1"

ARG FLASH_ATTN_WHEEL=flash_attn-2.8.3+cu13torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl
ARG FLASH_ATTN_URL=https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post1/flash_attn-2.8.3%2Bcu13torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl
ARG FLASH_ATTN_SHA256=14609b65ebddd28d5087434b01019c9be093c92d44fe95def97b9f28905081dc

RUN curl -fL --retry 5 --retry-all-errors --progress-bar \
        -o "/tmp/${FLASH_ATTN_WHEEL}" "${FLASH_ATTN_URL}" \
    && echo "${FLASH_ATTN_SHA256}  /tmp/${FLASH_ATTN_WHEEL}" | sha256sum -c - \
    && python -m pip install --no-cache-dir --no-deps "/tmp/${FLASH_ATTN_WHEEL}" \
    && rm "/tmp/${FLASH_ATTN_WHEEL}"

ARG RCLONE_VERSION=1.74.3

RUN curl -fsSLO "https://downloads.rclone.org/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-amd64.zip" \
    && curl -fsSLO "https://downloads.rclone.org/v${RCLONE_VERSION}/SHA256SUMS" \
    && grep " rclone-v${RCLONE_VERSION}-linux-amd64.zip$" SHA256SUMS | sha256sum -c - \
    && unzip "rclone-v${RCLONE_VERSION}-linux-amd64.zip" \
    && install -m 0755 "rclone-v${RCLONE_VERSION}-linux-amd64/rclone" /usr/local/bin/rclone \
    && rm -rf "rclone-v${RCLONE_VERSION}-linux-amd64" "rclone-v${RCLONE_VERSION}-linux-amd64.zip" SHA256SUMS

ARG LLAMAFACTORY_COMMIT=unknown
ARG LLAMAFACTORY_DIRTY=unknown

COPY --from=llamafactory /pyproject.toml /README.md /LICENSE /opt/llamafactory/
COPY --from=llamafactory /src /opt/llamafactory/src

RUN printf '%s\n' "${LLAMAFACTORY_COMMIT}" > /opt/llamafactory/FACTORY_SOURCE_COMMIT \
    && printf '%s\n' "${LLAMAFACTORY_DIRTY}" > /opt/llamafactory/FACTORY_SOURCE_DIRTY \
    && python -m pip install --no-cache-dir --no-deps "/opt/llamafactory"

WORKDIR /opt/factory-cloud-runner
COPY runner ./runner

RUN mkdir -p \
    /workspace/training_artifacts \
    /workspace/data \
    /workspace/models \
    /cache/huggingface \
    /cache/torch \
    /cache/compiled/triton \
    /cache/compiled/torchinductor \
    /cache/compiled/unsloth \
    /cache/wandb

LABEL org.opencontainers.image.title="FactoryCloudRunner" \
      org.opencontainers.image.description="Sealed LlamaFactory Nextcloud batch runner" \
      org.opencontainers.image.source="https://github.com/KeinNiemand/FactoryCloudRunner" \
      org.opencontainers.image.licenses="MIT" \
      io.factorycloudrunner.llamafactory.commit="${LLAMAFACTORY_COMMIT}" \
      io.factorycloudrunner.llamafactory.dirty="${LLAMAFACTORY_DIRTY}"

ENV LLAMAFACTORY_COMMIT="${LLAMAFACTORY_COMMIT}" \
    LLAMAFACTORY_DIRTY="${LLAMAFACTORY_DIRTY}" \
    LLAMAFACTORY_SEPARATE_EVAL=0 \
    HF_HOME=/cache/huggingface \
    HF_HUB_CACHE=/cache/huggingface/hub \
    HF_DATASETS_CACHE=/cache/huggingface/datasets \
    TORCH_HOME=/cache/torch \
    TRITON_CACHE_DIR=/cache/compiled/triton \
    TORCHINDUCTOR_CACHE_DIR=/cache/compiled/torchinductor \
    UNSLOTH_COMPILE_CACHE=/cache/compiled/unsloth

ENTRYPOINT ["python", "-m", "runner.main"]

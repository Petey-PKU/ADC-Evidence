FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501 \
    ADC_BOOTSTRAP_EMBEDDING_BACKEND=hashing \
    HF_HOME=/app/artifacts/models/huggingface

WORKDIR /app

ARG ADC_INSTALL_PROFILE=demo
ARG TORCH_CPU_INDEX=https://download.pytorch.org/whl/cpu

RUN addgroup --system adc && adduser --system --ingroup adc --uid 10001 adc

COPY pyproject.toml README.md ./
COPY src ./src
COPY data/sample ./data/sample
COPY data/annotations ./data/annotations
COPY configs ./configs

RUN python -m pip install --upgrade pip && \
    if [ "$ADC_INSTALL_PROFILE" = "full" ]; then \
        python -m pip install --index-url "$TORCH_CPU_INDEX" torch && \
        python -m pip install ".[rag,generation]"; \
    else \
        python -m pip install ".[generation]"; \
    fi && \
    mkdir -p data/processed artifacts/vector_index artifacts/models artifacts/evaluation && \
    chown -R adc:adc /app

ENV PYTHONPATH=/app/src

USER adc

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

CMD ["python", "-m", "adc_evidence.deploy"]

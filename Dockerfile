# =============================================================================
# Multi-stage Dockerfile for Vertex Agent
#
# Stage 1: dependencies — install Python packages
# Stage 2: runtime — copy source and run LangGraph API server
# =============================================================================

# ── Stage 1: Dependencies ─────────────────────────────────────────────
FROM langchain/langgraph-api:3.11 AS builder

# Copy dependency specification
COPY pyproject.toml /deps/dev/pyproject.toml
COPY README.md /deps/dev/README.md

# Install dependencies (layer cached unless pyproject.toml changes)
RUN --mount=type=cache,target=/root/.cache/uv \
    for dep in /deps/*; do \
        if [ -d "$dep" ]; then \
            PYTHONDONTWRITEBYTECODE=1 uv pip install --system --no-cache-dir -c /api/constraints.txt -e "$dep"; \
        fi; \
    done

# ── Stage 2: Runtime ──────────────────────────────────────────────────
FROM builder AS runtime

# Copy source code
COPY src/ /deps/dev/src/
COPY config/ /deps/dev/config/

# LangGraph server configuration
ENV LANGGRAPH_CHECKPOINTER='"postgres"'
ENV LANGSERVE_GRAPHS='{"agent": "/deps/dev/src/agent/server.py:graph"}'

# Ensure langgraph-api packages are not overwritten
RUN mkdir -p /api/langgraph_api /api/langgraph_runtime /api/langgraph_license && \
    touch /api/langgraph_api/__init__.py /api/langgraph_runtime/__init__.py /api/langgraph_license/__init__.py
RUN PYTHONDONTWRITEBYTECODE=1 uv pip install --system --no-cache-dir --no-deps -e /api

# Clean up build tools
RUN pip uninstall -y pip setuptools wheel 2>/dev/null || true
RUN rm -rf /usr/local/lib/python*/site-packages/pip* /usr/local/lib/python*/site-packages/setuptools* 2>/dev/null || true
RUN uv pip uninstall --system pip setuptools wheel 2>/dev/null; rm /usr/bin/uv /usr/bin/uvx 2>/dev/null || true

WORKDIR /deps/dev

# Default command — LangGraph API server
CMD ["langgraph", "serve", "--host", "0.0.0.0", "--port", "8000"]
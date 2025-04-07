ARG PYTHON_VERSION=3.11
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_CACHE_DIR=/tmp/uv-cache/
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp
ENV PATH=/tmp/.local/bin:$PATH

WORKDIR ${LAMBDA_TASK_ROOT}

COPY uv.lock uv.lock
COPY packages/item-gen/pyproject.toml pyproject.toml
COPY packages/item-gen/src/item_gen/ ${LAMBDA_TASK_ROOT}/item_gen/

RUN uv export --frozen --no-dev --no-editable --no-emit-workspace -o requirements.txt && \
  uv pip install --target ${LAMBDA_TASK_ROOT} -r requirements.txt && \
  uv tool install --with requests stactools;

CMD ["item_gen.handler.handler"]

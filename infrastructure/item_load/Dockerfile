ARG PYTHON_VERSION=3.11
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /asset

COPY uv.lock uv.lock
COPY packages/item-load/pyproject.toml pyproject.toml
COPY packages/item-load/src/item_load/ item_load/

RUN uv export --frozen --no-dev --no-editable --no-emit-workspace -o requirements.txt && \
  uv pip install --target /asset -r requirements.txt

CMD ["item_load.handler.handler"]

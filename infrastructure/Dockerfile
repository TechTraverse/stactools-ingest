ARG PYTHON_VERSION=3.11
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_CACHE_DIR=/tmp/uv-cache/
ENV UV_COMPILE_BYTECODE=1

WORKDIR /tmp

COPY pyproject.toml pyproject.toml
COPY uv.lock uv.lock
COPY README.md README.md
COPY src/stactools_uvx/ src/stactools_uvx/

RUN uv export --frozen --no-dev --no-editable --extra lambda -o requirements.txt && \
  uv pip install --target ${LAMBDA_TASK_ROOT} -r requirements.txt

WORKDIR ${LAMBDA_TASK_ROOT}
ENV HOME=/tmp
ENV PATH=/tmp/.local/bin:$PATH

RUN uv tool install --with requests stactools;
COPY infrastructure/handler.py ${LAMBDA_TASK_ROOT}/handler.py

CMD ["handler.handler"]

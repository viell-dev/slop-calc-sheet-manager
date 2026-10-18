FROM node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS node
FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY requirements-dev.txt /tmp/requirements-dev.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements-dev.txt

ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
CMD ["python", "tools/check.py"]

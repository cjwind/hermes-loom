# Hermes Loom — pure-stdlib sidecar, so there are NO pip dependencies to install.
# We just drop the package into the image and run it as a module. This sidesteps
# PEP 668 "externally-managed-environment" entirely: nothing is installed onto
# your host Python.
FROM python:3.12-slim

# Don't buffer stdout/stderr — logs show up live under `docker logs` / compose.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Paths Loom resolves from the environment. These point at the volumes that
    # docker-compose (or `docker run -v`) mounts; see README "Run with Docker".
    HERMES_HOME=/hermes \
    LOOM_HOME=/loom

WORKDIR /app
COPY hermes_loom/ ./hermes_loom/

# The local UI / API listens here when you run `serve`.
EXPOSE 8765

# `docker run <image> <subcommand …>` overrides the default below, e.g.
#   docker run --rm hermes-loom status
#   docker run --rm hermes-loom sync
ENTRYPOINT ["python", "-m", "hermes_loom"]

# Default action: serve the UI. Bind 0.0.0.0 *inside the container* so the
# published port is reachable from the host (the container is the isolation
# boundary; we still only publish to 127.0.0.1 on the host — see compose).
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]

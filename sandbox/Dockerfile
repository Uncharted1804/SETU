# SETU sandbox image: setu-sandbox:py311
#
# Blueprint section 10.3, fixing F5. python:3.11-slim does NOT contain
# openpyxl, so sheet_compute fails immediately against the stock image.
#
# Design rules enforced here:
#   - only the approved packages, pinned exactly
#   - no compilers left in the final image
#   - no package manager usable at runtime
#   - non-root user
#   - nothing downloaded at runtime
#
# Build:  docker build -t setu-sandbox:py311 sandbox/
# Export: docker save -o setu-sandbox-py311.tar setu-sandbox:py311

FROM python:3.11-slim AS builder

# Install into an isolated prefix we can copy wholesale into the final stage.
# --no-cache-dir keeps the wheel cache out of the layer.
RUN pip install --no-cache-dir --prefix=/install \
        openpyxl==3.1.5 \
        et-xmlfile==2.0.0 \
        numpy==2.1.3

# ----------------------------------------------------------------------------

FROM python:3.11-slim

COPY --from=builder /install /usr/local

# Strip the package manager so generated code cannot pip-install anything even
# if it somehow acquired network access. Also removes compilers and caches.
RUN rm -rf /usr/local/lib/python3.11/ensurepip \
           /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-* \
           /usr/local/lib/python3.11/site-packages/setuptools \
           /usr/local/lib/python3.11/site-packages/setuptools-* \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11 \
           /root/.cache /tmp/* /var/lib/apt/lists/* \
    && find /usr/local -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && rm -rf /usr/share/doc /usr/share/man

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1 \
    # HOME must be writable because the run profile uses --read-only.
    # /tmp is the only tmpfs mount, so point HOME there.
    HOME=/tmp \
    MPLCONFIGDIR=/tmp \
    NUMPY_MADVISE_HUGEPAGE=0

# nobody:nogroup = 65534:65534, matching --user in the run profile.
# Declared here as well so the image is safe even if a flag is ever dropped.
USER 65534:65534

WORKDIR /src

# Fail closed: if the orchestrator forgets to pass a command, do nothing useful.
ENTRYPOINT ["python", "-B"]
CMD ["-c", "raise SystemExit('setu-sandbox: no script supplied')"]

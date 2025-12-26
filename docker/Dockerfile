# docker/Dockerfile
# Executor image: Playwright browsers + deps are provided by the base image,
# but the Playwright Python package must be installed separately.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

# Keep it deterministic for students
RUN python -m pip install --no-cache-dir -U pip \
 && python -m pip install --no-cache-dir playwright==1.56.0

WORKDIR /work


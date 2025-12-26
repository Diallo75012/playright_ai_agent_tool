# install
```bash
pip install pytest-playwright
```
# Install the required browsers with dependencies and update it
```bash
playwright install
playwright install-deps
pip install pytest-playwright playwright -U
```

# README.md
# Shibuya Tokyo Cyberpunk — DOM-First Browser Agent (Groq + Playwright + Docker + Flask)

## Repo structure (top-level)
- app.py
- templates/
- static/
- artifacts/
- docker_work/
- docker/
- demo.db

## 1) Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) docker
```bash
sudo apt install docker-buildx
docker buildx build -t chikar-playwright-executor:latest -f docker/Dockerfile .
# NOTE: app.py default expects: chikar-playwright-executor:latest
# If you use another name, set EXECUTOR_IMAGE in .env
```

## 3) run
```bash
python3 app.py
```

# App Flow
Planner generates a plan to:
- open the ZenPath product page
- click Add to cart
- click View cart
- type into Order special instructions

Executor runs in Docker and writes:
- artifacts/<run_id>_final.png
- artifacts/<run_id>_output.json

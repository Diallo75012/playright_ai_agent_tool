# Chikara Houses:[website demo](https://chikarahouses.com)
Using this real website in order to test agent using browser.
Demo of own AI Agents are interacting witht he web using `playright` `python`.
Here we go in a product page, we add to cart and we get a message entered int he order 'special' messages.
We get as a result a JSON output but hte best is the screenshot showing that agents are using screenshots
only for targeted actions and not all the time as too costly in terms of token and dollars paid.
So screenshot are done if `panic!` error for the AI Agent to check or at the end to validate.
But not as I thought on every single actions....


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

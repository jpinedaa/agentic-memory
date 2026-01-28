FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -e ".[distributed]"

COPY src/ src/
COPY prompts/ prompts/
COPY main.py run_inference_agent.py run_validator_agent.py run_cli.py ./

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]

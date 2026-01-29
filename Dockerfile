FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY src/ src/
COPY prompts/ prompts/
COPY main.py run_node.py ./

CMD ["python", "run_node.py", "--capabilities", "store,llm", "--port", "9000"]

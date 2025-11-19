FROM node:22-slim AS node
FROM python:3.11-slim

# Copie Node.js depuis l'image node
COPY --from=node /usr/local /usr/local

# Install Python build dependencies
RUN apt-get update && apt-get install -y build-essential

# Vérifie les versions
RUN node -v && npm -v && python --version

RUN npm install -g @bitwarden/cli

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "app.bot"]

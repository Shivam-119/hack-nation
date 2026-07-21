# ---- Stage 1: build the React frontend into frontend/dist ----
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime (serves API + built frontend) ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000 VC_BRAIN_SEED=1

# Install deps first for layer caching (deps change less often than app code).
COPY pyproject.toml README.md ./
COPY vc_brain ./vc_brain
RUN pip install --no-cache-dir .

# App code + fixtures + entrypoint, then the built frontend from stage 1.
COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["python", "main.py"]

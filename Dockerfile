# --- Stage 1: Build frontend ---
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# --- Stage 2: Python backend ---
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY backend/ backend/
COPY config/ config/

# Copy built frontend into static/
COPY --from=frontend-build /app/frontend/dist /app/static

# Create data dir for SQLite
RUN mkdir -p /app/data

EXPOSE 8000

CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}

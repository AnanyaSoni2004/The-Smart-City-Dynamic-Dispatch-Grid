# ---- stage 1: build the React frontend ----
# node 25 / npm 11 — must match the npm that generated package-lock.json
FROM node:25-alpine AS webbuild
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- stage 2: Python runtime ----
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY dispatch_grid/ dispatch_grid/
COPY server/ server/
COPY --from=webbuild /app/web/dist web/dist

ENV PORT=8000
EXPOSE 8000
# shell form so $PORT (set by the host, e.g. Render) is expanded
CMD uvicorn server.app:app --host 0.0.0.0 --port ${PORT}

# Deployment Guide

## Docker Compose

```yaml
version: "3.9"

services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - postgres
      - redis
      - rabbitmq

  streamlit:
    build: .
    command: streamlit run src/entrypoints/streamlit_app/app.py --server.port 8501
    ports:
      - "8501:8501"
    environment:
      - API_BASE_URL=http://app:8000
    depends_on:
      - app

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: gd_integration
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "5672:5672"
      - "15672:15672"

volumes:
  pgdata:
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DB_HOST` | PostgreSQL host | `localhost` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_NAME` | Database name | `gd_integration` |
| `DB_USER` | Database user | `app` |
| `DB_PASSWORD` | Database password | — |
| `REDIS_HOST` | Redis host | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `QUEUE_HOST` | RabbitMQ host | `localhost` |
| `QUEUE_PORT` | RabbitMQ port | `5672` |
| `S3_ENDPOINT` | S3/MinIO endpoint | — |
| `S3_ACCESS_KEY` | S3 access key | — |
| `S3_SECRET_KEY` | S3 secret key | — |
| `API_BASE_URL` | Backend URL (for Streamlit) | `http://localhost:8000` |
| `CLICKHOUSE_HOST` | ClickHouse host | `localhost` |
| `ES_HOSTS` | Elasticsearch hosts (JSON) | `["http://localhost:9200"]` |

## Kubernetes

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gd-integration-tools
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gd-integration-tools
  template:
    metadata:
      labels:
        app: gd-integration-tools
    spec:
      containers:
        - name: app
          image: gd-integration-tools:latest
          ports:
            - containerPort: 8000
          livenessProbe:
            httpGet:
              path: /api/v1/health/liveness
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /api/v1/health/readiness
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
          startupProbe:
            httpGet:
              path: /api/v1/health/startup
              port: 8000
            failureThreshold: 30
            periodSeconds: 2
          envFrom:
            - secretRef:
                name: gd-integration-secrets
            - configMapRef:
                name: gd-integration-config
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: gd-integration-tools
spec:
  selector:
    app: gd-integration-tools
  ports:
    - port: 8000
      targetPort: 8000
  type: ClusterIP
```

## Monitoring

### Prometheus

Add scrape config:
```yaml
scrape_configs:
  - job_name: gd-integration-tools
    metrics_path: /metrics
    static_configs:
      - targets: ["gd-integration-tools:8000"]
```

### Graylog

Configure GELF UDP input on port 12201. Set env:
```
GRAYLOG_HOST=graylog.internal
GRAYLOG_PORT=12201
```

# Scaling Strategy

## Current Architecture Limits

| Component | Current | Bottleneck At |
|---|---|---|
| Django (Daphne) | Single process | ~500 concurrent WebSocket connections |
| Celery Workers | 1 worker, 4 threads | ~200 tasks/minute |
| PostgreSQL | Single instance | ~5,000 queries/second |
| Redis | Single instance | ~50,000 ops/second |

---

## Phase 1 — Vertical + Horizontal Workers (0→100K users)

### Actions
- Increase Celery worker count: `--scale worker=8`
- Separate queue workers: scheduler queue vs jobs queue vs default
- Add `--concurrency=8` per worker (gevent pool)
- Enable PostgreSQL connection pooling (PgBouncer)
- Add Redis `maxmemory-policy allkeys-lru`

```bash
# Scale workers via Docker Compose
docker compose up -d --scale worker=8 --scale beat=1
```

---

## Phase 2 — Read Replicas + Caching (100K→500K users)

### Database
- Add PostgreSQL read replica
- Route analytics/dashboard queries to replica
- Add `CONN_MAX_AGE=600` and `CONN_HEALTH_CHECKS=True` (already done)

### Caching
- Cache dashboard stats in Redis (5-minute TTL)
- Cache WhatsApp template lists per tenant
- Cache user JWT claims to reduce DB auth lookups

### Media
- Move `media/` to S3 / Cloudflare R2
- Add CDN (Cloudflare) for static assets

---

## Phase 3 — Horizontal API Scaling (500K→1M users)

### Load Balancing
```
                    Cloudflare
                        │
                  Nginx Load Balancer
                 /         │         \
         Daphne 1    Daphne 2    Daphne 3
                 \         │         /
                    PostgreSQL (primary)
                    Redis Cluster
```

### WebSocket Scaling
- All Daphne instances share Redis Channel Layer
- Messages routed via Redis pub/sub (already implemented)
- No sticky sessions needed

### Celery Scaling
- Dedicated machines for `jobs` queue workers
- Autoscale based on queue depth via Kubernetes HPA

---

## Key Metrics to Monitor

| Metric | Warning | Critical |
|---|---|---|
| API response time (p95) | > 500ms | > 2s |
| Celery queue depth | > 1000 | > 5000 |
| PostgreSQL connection count | > 80% of max | > 95% |
| Redis memory usage | > 70% | > 90% |
| Failed Celery tasks (1h) | > 10 | > 100 |
| WebSocket connection count | > 1000 | > 5000 |

See [observability/dashboards/](../../observability/dashboards/) for Grafana configs.

# Kontrak Layanan & Topologi Sintetis Chapter C03 (Service Contracts)

- **ID Bukti:** `E03` (`service-contracts`)
- **Run ID:** `c03-20261109T084600Z`
- **Referensi Skema C02:**
  - `urn:sre-sim:contract:service-catalog:1` (`service-catalog.v1.schema.json`)
  - `urn:sre-sim:contract:telemetry-log:1` (`telemetry-log.v1.schema.json`)
  - `urn:sre-sim:contract:telemetry-metric:1` (`telemetry-metric.v1.schema.json`)
  - `urn:sre-sim:contract:dependency-edge:1` (`dependency-edge.v1.schema.json`)

---

## 1. Inventaris 5 Microservices & 2 Komponen Pendukung

| ID Layanan / Komponen | Jenis | Komponen Katalog | Dependensi (`dependency_refs`) | Endpoint Utama |
|---|---|---|---|---|
| `api-gateway` | FastAPI Microservice (`#1`) | `gateway` | `["auth-service", "transaction-service"]` | `POST /api/v1/transactions`, `GET /api/v1/transactions/{tx_id}`, `GET /api/v1/notifications/{tx_id}`, `GET /api/v1/topology`, `/health/live`, `/health/ready`, `/metrics`, `/catalog` |
| `auth-service` | FastAPI Microservice (`#2`) | `auth` | `[]` | `POST /internal/auth/verify`, `/health/live`, `/health/ready`, `/metrics`, `/catalog` |
| `transaction-service` | FastAPI Microservice (`#3`) | `transaction` | `["ledger-service", "notification-service"]` | `POST /internal/transactions/execute`, `GET /internal/transactions/{tx_id}`, `/health/live`, `/health/ready`, `/metrics`, `/catalog` |
| `ledger-service` | FastAPI Microservice (`#4`) | `ledger` | `[]` (menggunakan `postgres` internal) | `POST /internal/ledger/entries`, `GET /internal/ledger/entries/{tx_id}`, `GET /internal/ledger/entries`, `/health/live`, `/health/ready`, `/metrics`, `/catalog` |
| `notification-service` | FastAPI Microservice (`#5`) | `notification_worker` | `[]` (mengonsumsi `rabbitmq` internal) | Background consumer RabbitMQ (`notifications.transaction.completed`), `POST /internal/notifications/consume`, `GET /internal/notifications`, `GET /internal/notifications/{tx_id}`, `/health/live`, `/health/ready`, `/metrics`, `/catalog` |
| `postgres` | Komponen Pendukung (Database) | `postgres:16-alpine` | Volume `sim_postgres_data` | Port internal `5432/tcp` (tidak diekspos ke host) |
| `rabbitmq` | Komponen Pendukung (Queue) | `rabbitmq:3.13-alpine` | Durable queue + DLQ | Port internal `5672/tcp` (tidak diekspos ke host) |

---

## 2. Kontrak Propagasi Konteks & Error Deterministik

1. **Header Propagasi:**
   - `X-Correlation-ID`: `^corr-[a-zA-Z0-9._:-]+$` diteruskan dari `api-gateway` ke `auth-service`, `transaction-service`, `ledger-service`, hingga payload RabbitMQ yang dikonsumsi `notification-service`.
   - `traceparent`: W3C Trace Context `00-<32-hex-trace-id>-<16-hex-span-id>-01` dengan `trace_id` yang sama di seluruh rantai sinkron dan asinkron.
2. **Envelope Error Standar:**
   - Setiap kegagalan validasi (`400`/`422`), otentikasi/otorisasi (`401`/`403`), konflik idempotensi (`409`), tidak ditemukan (`404`), maupun kegagalan dependensi (`503`) mengembalikan JSON deterministik:
     `{"error_code", "message", "service_id", "environment", "correlation_id", "trace_id", "span_id", "timestamp"}`.


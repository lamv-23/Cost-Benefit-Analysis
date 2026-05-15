# Production Readiness Plan — Multi-User Deployment

**Target**: Internal network Azure VM (32GB RAM, Xeon), no Docker, no IT dependency

> See the companion architecture doc for motivation and tradeoffs behind each decision.

---

## Prerequisites (do once on the VM)

- [ ] Install Python 3.11+ (if not present)
- [ ] Install PostgreSQL 16 (`apt install postgresql` or download)
- [ ] Install nginx (`apt install nginx`)
- [ ] Install `pip` dependencies: `pip install -r requirements.txt && pip install psycopg2-binary sentry-sdk`
- [ ] Generate self-signed TLS cert: `openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/cba.key -out /etc/ssl/certs/cba.crt`
- [ ] Create PostgreSQL database + user:
  ```sql
  CREATE DATABASE cba_projects;
  CREATE USER cba_user WITH PASSWORD 'change-me';
  GRANT ALL PRIVILEGES ON DATABASE cba_projects TO cba_user;
  ```
- [ ] Set up password file for nginx `auth_basic`:
  ```bash
  printf "cba:$(openssl passwd -apr1 '<shared-password>')\n" > /etc/nginx/.htpasswd
  ```

---

## ① Reverse Proxy (nginx + TLS + Auth)

- [ ] Write `/etc/nginx/sites-available/cba` with:
  - listen 443 ssl; http2 on
  - ssl_certificate / ssl_certificate_key pointing to self-signed cert
  - auth_basic "CBA Dashboard" + auth_basic_user_file
  - proxy_pass http://127.0.0.1:8501
  - rate limiting: limit_req_zone + limit_req
  - client_max_body_size 50M
  - proxy_read_timeout 120s
- [ ] Symlink and restart: `ln -s /etc/nginx/sites-available/cba /etc/nginx/sites-enabled/ && systemctl restart nginx`
- [ ] Open firewall for port 443 (internal network only)

## ② Persistent Database (PostgreSQL + Project Store)

- [ ] Create `src/lib/project_store.py`:
  - SQLAlchemy or psycopg2 connection pool
  - Table `projects`: id (UUID PK), name, data (JSONB), created_at, updated_at
  - Functions: `save_project(name, data_dict) -> project_id`, `load_project(project_id) -> dict`, `list_projects() -> list`, `delete_project(project_id)`
- [ ] Add environment variable `DATABASE_URL=postgresql://cba_user:change-me@localhost:5432/cba_projects`
- [ ] Add "Save Project" / "Load Project" UI to `app.py` sidebar
- [ ] Wire `_serialise_project()` to call `project_store.save_project()`
- [ ] Wire `_deserialise_project()` to call `project_store.load_project()`

## ③ Auth Layer (Streamlit Login Page)

- [ ] Add login screen to `app.py` (before page config or at top of main flow):
  - Check `st.session_state["authenticated"]`
  - If not authenticated, show password input form
  - Compare password against `os.environ.get("APP_PASSWORD", "cba")`
  - On success: `st.session_state["authenticated"] = True`, `st.rerun()`
  - All app code guarded behind this check
- [ ] Set `APP_PASSWORD` environment variable on the VM (add to systemd env or `.env` file)

## ④ Resource Governance

- [ ] Cap Monte Carlo iterations: default 500, slider range 100–2000
- [ ] Add memory check in `run_monte_carlo()`: warn if `n_simulations * expected_mb > available_ram * 0.5`
- [ ] Add session timeout note to nginx config (`proxy_read_timeout 86400s` for long sessions)
- [ ] Add rate-limiting zone to nginx config (10 req/s per IP, burst 20)
- [ ] Add concurrent connection limit to nginx config (`limit_conn addr 50`)

## ⑤ Observability

- [ ] Add Python logging to `app.py`:
  - `logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')`
  - Log calculation starts, save/load events, auth attempts (without passwords)
  - Rotating file handler: `/var/log/cba-dashboard/app.log`
- [ ] Add optional Sentry integration: `sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN", ""))`
- [ ] Verify Streamlit health endpoint `/_stcore/health` works through nginx
- [ ] Add `pg_dump` cron job for PostgreSQL backup:
  ```cron
  0 3 * * * pg_dump cba_projects > /backups/cba/cba_$(date +\%Y\%m\%d).sql
  ```

## ⑥ Multi-Worker (if needed for >20 concurrent users)

- [ ] Only if single-process Streamlit shows CPU/memory pressure
- [ ] Create systemd service for Streamlit (not a background process)
- [ ] Can add a second Streamlit worker behind nginx with sticky sessions (ip_hash) if needed

---

## Deployment One-Liner

```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt &&
pip install psycopg2-binary sentry-sdk &&
export APP_PASSWORD='<shared-password>' DATABASE_URL='postgresql://cba_user:change-me@localhost:5432/cba_projects' &&
streamlit run app.py --server.port=8501 --server.address=127.0.0.1 --server.maxUploadSize=50
```

(nginx + PostgreSQL services must be running separately)

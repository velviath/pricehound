# PriceHound 🐶

A full-stack price-tracking web app with AI insights. Paste any product URL, set a target price, and get an email when the price drops.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Database | PostgreSQL + asyncpg (raw SQL, no ORM) |
| Scraping | httpx + BeautifulSoup4 + lxml |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Email | aiosmtplib |
| AI Insights | OpenAI GPT-4o-mini |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Frontend | Vanilla HTML / CSS / JS + Chart.js |

## Project Structure

```
pricehound/
├── main.py                  # FastAPI app + lifespan (DB init, scheduler)
├── config.py                # Settings via pydantic-settings / .env
├── auth/
│   ├── routes.py            # POST /auth/register, POST /auth/login
│   └── utils.py             # JWT helpers, password hashing, FastAPI deps
├── api/
│   ├── products.py          # Product endpoints
│   ├── alerts.py            # Alert CRUD
│   └── dashboard.py        # GET /api/dashboard/
├── services/
│   ├── parser.py            # Universal price scraper
│   ├── scheduler.py         # APScheduler job — re-checks prices every N hours
│   ├── email_service.py     # HTML alert emails via aiosmtplib
│   └── openai_service.py    # GPT-4o-mini price insight
├── database/
│   ├── connection.py        # asyncpg pool + DDL
│   ├── models.py            # Pydantic request/response models
│   └── queries.py           # All SQL queries as async functions
├── static/
│   ├── index.html           # Landing page (split layout + tracking form)
│   ├── product.html         # Product detail + chart + AI insight + alert modal
│   ├── dashboard.html       # User dashboard
│   └── login.html           # Login / register tabs
├── .env.example
├── requirements.txt
└── README.md
```

## Local Setup

### Prerequisites

- Python 3.11+
- PostgreSQL running locally (or a connection string to a remote DB)

### 1. Clone & install

```bash
git clone <repo-url>
cd pricehound
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL
```

### 3. Create the database

```bash
psql -U postgres -c "CREATE DATABASE pricehound;"
```

Tables are created automatically on first startup via `database/connection.py`.

### 4. Run

```bash
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | — | Create account, returns JWT |
| `POST` | `/auth/login` | — | Login, returns JWT |
| `GET` | `/api/products/recent` | — | Last 3 tracked products (landing page) |
| `POST` | `/api/products/track` | — | Parse URL and start tracking |
| `GET` | `/api/products/{id}` | — | Product detail + history + AI insight |
| `GET` | `/api/products/{id}/history` | — | Price history for Chart.js |
| `DELETE` | `/api/products/{id}` | — | Delete product |
| `POST` | `/api/alerts/` | JWT | Create price alert |
| `DELETE` | `/api/alerts/{id}` | JWT | Delete alert |
| `PATCH` | `/api/alerts/{id}/target` | JWT | Update target price |
| `GET` | `/api/dashboard/` | JWT | Full dashboard data |

## Deployment

### Docker (recommended)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Set environment variables (DATABASE_URL, JWT_SECRET, etc.) in your container platform.

### Railway / Render / Fly.io

1. Push the repo.
2. Set env vars in the platform dashboard.
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## Parser Coverage

The scraper tries these strategies in order:

1. `og:price:amount` Open Graph meta tag
2. Schema.org JSON-LD (`offers.price`)
3. Amazon-specific CSS selectors
4. Common price CSS class heuristics (`price`, `offer-price`, etc.)

Sites that render prices via JavaScript (heavy SPAs) may not be parseable without a headless browser.

## Email Alerts

Uses Gmail SMTP with App Passwords. Generate one at:
`Google Account → Security → 2-Step Verification → App passwords`

Set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER` and `SMTP_PASSWORD` in `.env`.

## AI Insights

Requires an OpenAI API key. Uses `gpt-4o-mini` — very cheap (fractions of a cent per call). Set `OPENAI_API_KEY` in `.env`. Insight generation is non-blocking; the product page still works without it.

# Tradiopro

Tradiopro is a forex and cryptocurrency analysis tool. Its planned analysis flow
combines deterministic market and risk validation with AI-generated
explanations. The initial release will not place live orders.

## Phase 1 foundation

- `apps/web`: Next.js App Router frontend written in TypeScript.
- `services/analysis`: Python FastAPI analysis-service foundation.
- Supabase is the planned provider for PostgreSQL, authentication, and
  user-specific data. Database access, authentication flows, and row-level
  security policies have not been implemented yet.
- Background monitoring, market-data integrations, and AI explanations have
  not been implemented yet.

## Run the frontend

```powershell
cd apps\web
npm.cmd install
npm.cmd run dev
```

Open <http://localhost:3000>.

## Run the analysis service

From the repository root, create and activate a Python virtual environment,
then install the service and its test dependencies:

```powershell
python -m venv services\analysis\.venv
services\analysis\.venv\Scripts\Activate.ps1
python -m pip install -e "services\analysis[dev]"
python -m uvicorn tradiopro_analysis.main:app --app-dir services\analysis\src --reload
```

The service health endpoint is available at <http://127.0.0.1:8000/health>.

## Configuration and security

Copy `.env.example` to a local environment file when configuration is needed.
Never commit secrets or expose Supabase service-role credentials through
`NEXT_PUBLIC_*` variables. The frontend currently does not require Supabase
credentials to start.

The analysis API allows browser requests only from the configured
`FRONTEND_ORIGIN` (default: `http://localhost:3000`). Set it to the exact
frontend origin when deploying.

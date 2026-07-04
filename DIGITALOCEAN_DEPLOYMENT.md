# DigitalOcean Deployment

This app is ready for DigitalOcean App Platform.

## App Platform

The app spec lives at `.do/app.yaml` and creates:

- one Node.js web service
- one managed PostgreSQL database
- `/api/health` as the health check
- one ingress rule that routes `/` to the web service

Build command:

```sh
npm ci && npm run build
```

Run command:

```sh
npm start
```

## Required Environment Variables

Set these in DigitalOcean App Platform:

- `DATABASE_URL` - supplied by the `fuelpoints-db` managed database
- `PGSSLMODE=require`
- `GOOGLE_MAPS_API_KEY`
- `SMTP_USER`
- `SMTP_PASSWORD`

`NODE_ENV=production` is already set in the app spec.

The production database is configured with `cluster_name: fuelpoints-db-cluster`, `db_name: fuelpoints`, and `db_user: fuelpoints`. Rename those in `.do/app.yaml` if you want to attach an existing DigitalOcean database cluster instead.

## Database Setup

After the DigitalOcean database is created, apply the schema:

```sh
DATABASE_URL="postgres://..." npm run db:push
```

To copy data from an existing database into the DigitalOcean database:

```sh
DATABASE_URL="postgres://current-db" PRODUCTION_DATABASE_URL="postgres://digitalocean-db?sslmode=require" npx tsx scripts/migrate-to-production.ts
```

## Notes

- The server binds to `0.0.0.0` and uses DigitalOcean's `PORT` env var when present.
- The production server serves the Vite build from `dist` and falls back to `index.html` for client-side routes.
- `Dockerfile` is included as a fallback deployment path if you prefer a containerized DigitalOcean App Platform service.

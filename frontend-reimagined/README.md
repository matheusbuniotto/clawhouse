# Clawhouse UI (Lovable mirror)

Synced from Lovable project **OpenClaw UI Reimagined**.

## Local development

```sh
cd frontend-reimagined
bun install
bun run dev
```

Point the UI at a Clawhouse API with `VITE_API_BASE=http://localhost:8000` (or leave empty when the dev server proxies API requests).

## Lovable editor

https://lovable.dev/projects/6acfffed-70f8-49b2-ba3e-72b458c15fc0

## Re-sync from Lovable

From the repo root (requires `LOVABLE_API_KEY`):

```sh
LOVABLE_API_KEY=… node scripts/sync-lovable-frontend.mjs
```

---

# Welcome to your Lovable project

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Open your project in the [Lovable editor](https://lovable.dev) and keep building.

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: connect the project to GitHub and every change made in Lovable is committed straight to your repository.
- **Full ownership**: this code is yours. Push to your repository and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```

## Built with

- TanStack Start
- TypeScript
- React
- Tailwind CSS

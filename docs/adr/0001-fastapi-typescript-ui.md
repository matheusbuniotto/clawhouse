# ADR-0001: FastAPI backend with TypeScript/HTML frontend

Date: 2026-10-10
Status: accepted

## Context

DatabricksClaw MVP needs a single chat entry surface as a Databricks App. Options were FastAPI, Flask, Dash, Streamlit for backend/UI, with a separate question of TypeScript/HTML vs framework-native UI.

## Decision

- Backend: FastAPI — typed API for chat + tool dispatch, fits Databricks Apps hosting.
- Frontend: TypeScript (or plain HTML) served by the App. No Dash/Streamlit native UI in v1.

## Consequences

- Turn orchestration is exposed as an API consumed by the TS frontend; streaming transport is framework-specific and out of the core turn contract.
- Dash/Streamlit components are out of scope for MVP.

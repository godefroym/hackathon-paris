# OBS Controller

This is a Laravel-based application that acts as the bridge between the AI analysis and the live broadcast.

## Role
- Receives fact-check results from the Temporal workflow via its API.
- Manages the live "bandeau" (banner) displayed on screen.
- Communicates with OBS (Open Broadcaster Software) via WebSockets to trigger scene changes or update text sources in real-time.

## Tech Stack
- **Framework**: Laravel (PHP)
- **Database**: MySQL/PostgreSQL (depending on setup)
- **Communication**: OBS WebSocket

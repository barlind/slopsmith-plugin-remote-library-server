# Slopsmith Remote Library Server

Remote Library Server is the source-side Slopsmith plugin for sharing a local song library over a small direct HTTP API. It runs on its own port, separate from Slopsmith's main backend, so a tunnel can expose only the library-source API.

## What It Does

- Starts a direct library server on a configurable host and port.
- Lists local PSARC and Sloppak packages as remote song summaries.
- Serves artwork for a song.
- Serves the original package file for sync/download.
- Allows a client plugin to connect by base URL.

No relay, pairing, approval flow, or published catalog is used in this first version.

## Direct Flow

```mermaid
flowchart LR
  Client[Slopsmith client plugin] -->|GET /source| Server[Remote Library Server]
  Client -->|GET /songs?q=...| Server
  Client -->|GET /songs/{id}/art| Server
  Client -->|GET /songs/{id}/package| Server
```

## API

When the server is running, the client only needs the server base URL, for example `http://127.0.0.1:8765` or an ngrok URL.

- `GET /health`
- `GET /source`
- `GET /songs?q=&pageSize=50&cursor=0`
- `GET /songs/{remoteSongId}/art`
- `GET /songs/{remoteSongId}/package?packageHash=sha256:...`

## Settings

- `enabled`: starts the direct server when the plugin loads.
- `host`: bind host. Use `127.0.0.1` for local-only tunnels or `0.0.0.0` for LAN access.
- `port`: bind port. Default: `8765`.
- `sourceName`: display name returned by `/source`.
- `publicUrl`: optional external URL shown in status.

## Tunneling

Expose only the direct server port:

```bash
ngrok http 8765
```

Point the client plugin at the resulting base URL.

Direct mode has no authentication or pairing in this version. Treat the URL as access to the shared library surface.

## Development

Run the focused tests from this plugin directory:

```bash
pytest
```
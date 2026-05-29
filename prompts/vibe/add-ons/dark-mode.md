### Add-on: Dark Mode

Ship light + dark themes. Default to `prefers-color-scheme` for first
visit and a manual toggle (persisted to `localStorage`). Theme via CSS
variables so the app doesn't have to thread a context through every
component. Ensure all components — including third-party ones — pass
contrast in both modes.

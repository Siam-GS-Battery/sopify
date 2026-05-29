### Add-on: Authentication (JWT)

Include sign-in / sign-out and a JWT-based session for protected routes.
Default to a self-issued token from the local backend (Supabase Auth if
the Database add-on is also picked). Store the token in `localStorage`
unless the user wants stricter cookie-based handling.

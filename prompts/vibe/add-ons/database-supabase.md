### Add-on: Database (Supabase Local)

Use the Supabase Local stack (already installed alongside Sopify) as the
data layer. Stand up tables, RLS policies, and a typed client. Prefer
the Supabase JS SDK directly from the frontend for reads, and a thin
backend layer for writes that need server-side validation.

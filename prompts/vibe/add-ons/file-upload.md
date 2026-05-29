### Add-on: File Upload

Support uploading files (images, PDFs, etc.) from the UI. Default to drag-
and-drop with a click-to-pick fallback. Show progress while uploading.
Validate size and MIME type client-side and again on the server. If
Database (Supabase) is also enabled, use Supabase Storage as the
destination; otherwise stub a local upload endpoint.

### Add-on: QR Scan

Add a QR-code scanner using the device camera. Default to the
`getUserMedia` API with a lightweight in-browser decoder (e.g.
`jsQR`/`html5-qrcode`). Ask permission once and remember it. Handle the
"no camera" case (desktop without webcam) with a clear empty state and
an optional image-upload fallback (decode a QR from a photo).

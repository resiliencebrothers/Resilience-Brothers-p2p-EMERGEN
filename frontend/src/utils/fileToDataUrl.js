/**
 * iter102 — Turn a File (from <input type="file">) into a base64 data URL
 * the backend expects (see `services/proof_upload.py::maybe_upload_proof`).
 *
 * Kept small on purpose: the KYC uploader already does something similar
 * but that helper is tied to KYC-specific state.
 */
export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** Client-side pre-flight: keep image below 8 MB (backend hard cap). */
export function isImageTooLarge(file, maxMb = 8) {
  return file.size > maxMb * 1024 * 1024;
}

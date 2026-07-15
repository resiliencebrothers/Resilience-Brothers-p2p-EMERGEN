/**
 * extractDetailMessage — iter55.36o
 *
 * FastAPI returns structured `detail` objects for guarded endpoints, e.g.
 *   { code: "KYC_NOT_APPROVED", message: "...", missing: [...], cta_url: "..." }
 *
 * Passing that raw object to `toast.error(...)` crashes React because
 * objects are not valid children. This helper safely extracts a human
 * message from either a string, an object with `.message`, or a fallback.
 *
 * Usage:
 *   } catch (e) {
 *     toast.error(extractDetailMessage(e, "Error al crear orden"));
 *   }
 */
export function extractDetailMessage(error, fallback = "Error") {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") {
    return detail.message;
  }
  if (typeof error?.message === "string") return error.message;
  return fallback;
}

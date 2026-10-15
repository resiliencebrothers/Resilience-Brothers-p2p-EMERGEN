// Base del panel según el rol: Empresa vive en /company; el resto en /dashboard.
// Centraliza el destino de las pantallas comunes de Verificación/Seguridad para
// que los CTA no envíen a Empresa a /dashboard/* (que su router devuelve a /company).
export function profileBase(role) {
  return role === "empresa" ? "/company" : "/dashboard";
}

// Para contextos sin acceso directo al rol (interceptor global, diálogos
// reutilizados): deriva la base del panel activo a partir de la URL actual.
export function currentPanelBase() {
  if (typeof window !== "undefined" && window.location.pathname.startsWith("/company")) {
    return "/company";
  }
  return "/dashboard";
}

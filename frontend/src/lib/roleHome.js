// Ruta de inicio según el rol tras iniciar sesión.
// Empresa (rol business) tiene su propio panel independiente en /company.
export function roleHome(user) {
  if (!user) return "/";
  if (user.role === "admin" || user.role === "employee") return "/admin";
  if (user.role === "empresa") return "/company";
  return "/dashboard";
}

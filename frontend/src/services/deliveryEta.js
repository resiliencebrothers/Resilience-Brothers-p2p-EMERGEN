// Cálculo compartido de ETA de mensajería (cliente + staff).
// Aproximación: distancia línea recta × factor vial 1.4 a ~22 km/h urbano.

export function distKm(a, b) {
  const R = 6371, toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(h));
}

// Acepta docs de admin (courier_location plano) y de tracking (courier.location).
export function etaFromDelivery(d) {
  const loc = d.courier_location || d.courier?.location;
  if (!loc || d.delivery_latitude == null || d.delivery_longitude == null) return null;
  const km = distKm(loc, { lat: d.delivery_latitude, lon: d.delivery_longitude });
  const min = Math.max(1, Math.round(((km * 1.4) / 22) * 60));
  let ageMin = null;
  if (loc.updated_at) {
    const age = (Date.now() - new Date(loc.updated_at).getTime()) / 60000;
    if (Number.isFinite(age) && age >= 0) ageMin = Math.round(age);
  }
  return { min, km, ageMin };
}

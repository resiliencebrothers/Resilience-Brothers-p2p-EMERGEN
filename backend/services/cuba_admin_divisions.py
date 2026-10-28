"""Catálogo estático de la división político-administrativa de Cuba
(provincias → municipios). Sirve a la herramienta del admin para activar
entregas en una provincia completa de un golpe: se elige la provincia, se ven
todos sus municipios y se fija un precio por cada uno. No es la fuente de
tarifas (esas viven en `courier_municipality_rates`); es solo el listado de
referencia para cargarlas rápido.

La Habana usa los nombres que ya emplea el operador en las tarifas sembradas
para que la herramienta los detecte como "ya configurados".
"""

CUBA_PROVINCES: dict[str, list[str]] = {
    "Pinar del Río": [
        "Consolación del Sur", "Guane", "La Palma", "Los Palacios", "Mantua",
        "Minas de Matahambre", "Pinar del Río", "San Juan y Martínez",
        "San Luis", "Sandino", "Viñales",
    ],
    "Artemisa": [
        "Alquízar", "Artemisa", "Bahía Honda", "Bauta", "Caimito",
        "Candelaria", "Guanajay", "Güira de Melena", "Mariel",
        "San Antonio de los Baños", "San Cristóbal",
    ],
    "La Habana": [
        "10 de Octubre", "Vedado", "Cerro", "Habana Vieja", "Centro Habana",
        "Plaza", "Regla", "Arroyo Naranjo", "San Miguel del Padrón",
        "Guanabacoa", "Cotorro", "Boyeros", "Habana del Este", "Marianao",
        "La Lisa",
    ],
    "Mayabeque": [
        "Batabanó", "Bejucal", "Güines", "Jaruco", "Madruga",
        "Melena del Sur", "Nueva Paz", "Quivicán", "San José de las Lajas",
        "San Nicolás de Bari", "Santa Cruz del Norte",
    ],
    "Matanzas": [
        "Calimete", "Cárdenas", "Ciénaga de Zapata", "Colón", "Jagüey Grande",
        "Jovellanos", "Limonar", "Los Arabos", "Martí", "Matanzas",
        "Pedro Betancourt", "Perico", "Unión de Reyes",
    ],
    "Cienfuegos": [
        "Abreus", "Aguada de Pasajeros", "Cienfuegos", "Cruces",
        "Cumanayagua", "Lajas", "Palmira", "Rodas",
    ],
    "Villa Clara": [
        "Caibarién", "Camajuaní", "Cifuentes", "Corralillo", "Encrucijada",
        "Manicaragua", "Placetas", "Quemado de Güines", "Ranchuelo",
        "Remedios", "Sagua la Grande", "Santa Clara", "Santo Domingo",
    ],
    "Sancti Spíritus": [
        "Cabaiguán", "Fomento", "Jatibonico", "La Sierpe", "Sancti Spíritus",
        "Taguasco", "Trinidad", "Yaguajay",
    ],
    "Ciego de Ávila": [
        "Baraguá", "Bolivia", "Chambas", "Ciego de Ávila", "Ciro Redondo",
        "Florencia", "Majagua", "Morón", "Primero de Enero", "Venezuela",
    ],
    "Camagüey": [
        "Camagüey", "Carlos Manuel de Céspedes", "Esmeralda", "Florida",
        "Guáimaro", "Jimaguayú", "Minas", "Najasa", "Nuevitas",
        "Santa Cruz del Sur", "Sibanicú", "Sierra de Cubitas", "Vertientes",
    ],
    "Las Tunas": [
        "Amancio", "Colombia", "Jesús Menéndez", "Jobabo", "Las Tunas",
        "Majibacoa", "Manatí", "Puerto Padre",
    ],
    "Holguín": [
        "Antilla", "Báguanos", "Banes", "Cacocum", "Calixto García", "Cueto",
        "Frank País", "Gibara", "Holguín", "Mayarí", "Moa", "Rafael Freyre",
        "Sagua de Tánamo", "Urbano Noris",
    ],
    "Granma": [
        "Bartolomé Masó", "Bayamo", "Buey Arriba", "Campechuela",
        "Cauto Cristo", "Guisa", "Jiguaní", "Manzanillo", "Media Luna",
        "Niquero", "Pilón", "Río Cauto", "Yara",
    ],
    "Santiago de Cuba": [
        "Contramaestre", "Guamá", "Mella", "Palma Soriano", "San Luis",
        "Santiago de Cuba", "Segundo Frente", "Songo-La Maya", "Tercer Frente",
    ],
    "Guantánamo": [
        "Baracoa", "Caimanera", "El Salvador", "Guantánamo", "Imías", "Maisí",
        "Manuel Tames", "Niceto Pérez", "San Antonio del Sur", "Yateras",
    ],
    "Isla de la Juventud": [
        "Isla de la Juventud",
    ],
}

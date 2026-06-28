const ITEMS = [
  { key: "can_edit_product_prices", label: "Precios", title: "Puede modificar precios y costos de productos" },
  { key: "can_upload_product_images", label: "Imágenes", title: "Puede cambiar la URL de imagen promocional" },
  { key: "can_delete_products", label: "Eliminar", title: "Puede eliminar productos del catálogo" },
  { key: "can_manage_blocklist", label: "Bloqueos", title: "Puede ver y gestionar la lista de bloqueos, y verificar/rechazar teléfonos de usuarios" },
];

export function MarketPermsCell({ user, onToggle }) {
  return (
    <div className="flex flex-col gap-1.5" data-testid={`market-perms-${user.user_id}`}>
      {ITEMS.map(({ key, label, title }) => {
        const on = !!user[key];
        return (
          <label
            key={key}
            title={title}
            className={`flex items-center gap-2 cursor-pointer select-none text-xs ${on ? "text-[#22C55E]" : "text-neutral-500"}`}
          >
            <input
              type="checkbox"
              checked={on}
              onChange={(e) => onToggle(key, e.target.checked)}
              data-testid={`market-perm-${key}-${user.user_id}`}
              className="accent-[#EAB308] w-3.5 h-3.5"
            />
            <span className="font-mono">{label}</span>
          </label>
        );
      })}
    </div>
  );
}

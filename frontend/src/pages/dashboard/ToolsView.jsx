import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import ToolsPanel from "./tools/ToolsPanel";

// Herramientas en el dashboard de cliente: EXCLUSIVA de VIP (los clientes
// normales no acceden). Empresa tiene su propia pestaña en /company.
export default function ToolsView() {
  const { user } = useAuth();
  if (user && user.role !== "vip") return <Navigate to="/dashboard" replace />;
  return <ToolsPanel />;
}

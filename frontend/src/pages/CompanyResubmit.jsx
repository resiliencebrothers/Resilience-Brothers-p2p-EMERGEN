import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import CompanySignupDialog from "@/components/CompanySignupDialog";
import { Loader2, XCircle, Search } from "lucide-react";

export default function CompanyResubmit() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState("loading"); // loading | ready | err
  const [prefill, setPrefill] = useState(null);
  const [err, setErr] = useState("");
  const didRun = useRef(false);

  useEffect(() => {
    if (didRun.current) return;
    didRun.current = true;
    axios.get(`${API}/company-signup/resubmit/${token}`)
      .then((r) => { setPrefill(r.data); setState("ready"); })
      .catch((e) => { setErr(e.response?.data?.detail || "Enlace no válido, caducado o ya utilizado."); setState("err"); });
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] text-white p-4" data-testid="company-resubmit-page">
      {state === "loading" && (
        <div className="tactile-card p-10 max-w-md w-full text-center">
          <Loader2 className="w-10 h-10 text-[#8B5CF6] animate-spin mx-auto mb-4" />
          <p className="text-neutral-400">Cargando tu solicitud…</p>
        </div>
      )}
      {state === "err" && (
        <div className="tactile-card p-10 max-w-md w-full text-center" data-testid="company-resubmit-error">
          <XCircle className="w-12 h-12 text-[#EF4444] mx-auto mb-4" />
          <h1 className="font-display text-2xl mb-2">Enlace no válido</h1>
          <p className="text-neutral-400 text-sm mb-6">{err}</p>
          <Link to="/empresa/seguimiento" className="inline-flex items-center gap-1.5 text-[#8B5CF6] hover:underline text-sm" data-testid="company-resubmit-track-link">
            <Search className="w-4 h-4" /> Consultar el estado de mi solicitud
          </Link>
        </div>
      )}
      {state === "ready" && prefill && (
        <CompanySignupDialog
          open
          prefill={prefill}
          resubmitToken={token}
          rejectionReason={prefill.rejection_reason || ""}
          onClose={() => navigate("/", { replace: true })}
        />
      )}
    </div>
  );
}

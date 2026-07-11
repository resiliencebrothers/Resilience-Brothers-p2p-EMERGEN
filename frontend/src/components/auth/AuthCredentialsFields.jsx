import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Mail, Lock, User as UserIcon, Eye, EyeOff, Phone } from "lucide-react";

export function AuthCredentialsFields({
  mode,
  name, setName,
  phone, setPhone,
  email, setEmail,
  password, setPassword,
  confirmPassword, setConfirmPassword,
  showPassword, setShowPassword,
  nameInputRef,
  onEmailChange,
}) {
  const isRegister = mode === "register";
  const isForgot = mode === "forgot";

  return (
    <>
      {isRegister && (
        <div>
          <Label className="micro-label text-neutral-500">Nombre</Label>
          <div className="relative mt-1">
            <UserIcon className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              ref={nameInputRef}
              data-testid="auth-name-input"
              required
              minLength={2}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Tu nombre"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9"
            />
          </div>
        </div>
      )}

      {isRegister && (
        <div>
          <Label className="micro-label text-neutral-500">Teléfono</Label>
          <div className="relative mt-1">
            <Phone className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              data-testid="auth-phone-input"
              type="tel"
              required
              inputMode="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+5350123456 (con código de país)"
              autoComplete="tel"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9 font-mono"
            />
          </div>
          <p className="text-[0.65rem] text-neutral-600 mt-1">
            Un miembro del staff verificará tu número antes de habilitar retiros.
          </p>
        </div>
      )}

      <div>
        <Label className="micro-label text-neutral-500">Email</Label>
        <div className="relative mt-1">
          <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
          <Input
            data-testid="auth-email-input"
            type="email"
            required
            value={email}
            onChange={(e) => { setEmail(e.target.value); onEmailChange?.(); }}
            placeholder="tu@email.com"
            autoComplete="email"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9"
          />
        </div>
      </div>

      {!isForgot && (
        <div>
          <Label className="micro-label text-neutral-500">Contraseña</Label>
          <div className="relative mt-1">
            <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              data-testid="auth-password-input"
              type={showPassword ? "text" : "password"}
              required
              minLength={isRegister ? 8 : 1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isRegister ? "mín. 8 caracteres" : "Tu contraseña"}
              autoComplete={isRegister ? "new-password" : "current-password"}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9 pr-10"
            />
            <button
              type="button"
              data-testid="auth-toggle-password-visibility"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-neutral-500 hover:text-[#8B5CF6] transition-colors"
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
      )}

      {isRegister && (
        <div>
          <Label className="micro-label text-neutral-500">Confirmar contraseña</Label>
          <div className="relative mt-1">
            <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              data-testid="auth-confirm-password-input"
              type={showPassword ? "text" : "password"}
              required
              minLength={8}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Repite la contraseña"
              autoComplete="new-password"
              className={`rounded-none bg-[#0a0a0a] h-11 pl-9 ${
                confirmPassword && confirmPassword !== password
                  ? "border-[#EF4444]"
                  : "border-white/10"
              }`}
            />
          </div>
          {confirmPassword && confirmPassword !== password && (
            <p data-testid="auth-password-mismatch" className="text-[0.7rem] text-[#EF4444] mt-1">
              Las contraseñas no coinciden.
            </p>
          )}
        </div>
      )}
    </>
  );
}

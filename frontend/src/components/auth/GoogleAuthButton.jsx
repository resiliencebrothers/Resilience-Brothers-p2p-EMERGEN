export function GoogleAuthButton({ onClick }) {
  return (
    <button
      type="button"
      data-testid="auth-google-btn"
      onClick={onClick}
      className="w-full border border-white/20 hover:border-[#EAB308] hover:bg-white/5 text-white rounded-none h-11 text-sm font-semibold flex items-center justify-center gap-2 transition-colors"
    >
      <svg className="w-4 h-4" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
        <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.4 6.2 29.5 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
        <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 16.2 19 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.4 6.2 29.5 4 24 4c-7.7 0-14.3 4.4-17.7 10.7z" />
        <path fill="#4CAF50" d="M24 44c5.3 0 10.1-2 13.8-5.4l-6.4-5.4C29.2 35 26.7 36 24 36c-5.1 0-9.5-3.2-11.2-7.8l-6.5 5C9.6 39.6 16.3 44 24 44z" />
        <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.7l6.4 5.4C42 35 44 30 44 24c0-1.3-.1-2.4-.4-3.5z" />
      </svg>
      Continuar con Google
    </button>
  );
}

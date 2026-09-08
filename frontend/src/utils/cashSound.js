// iter225 — "Sonido de caja": campanita suave sintetizada con WebAudio
// (sin assets externos) cuando entra dinero al saldo del cliente.
let ctx = null;

export function playCashSound() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    ctx = ctx || new AC();
    if (ctx.state === "suspended") ctx.resume();
    const now = ctx.currentTime;
    const notes = [
      [1318.5, 0],     // E6
      [1760.0, 0.09],  // A6 — el "ka-ching"
    ];
    notes.forEach(([freq, delay]) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, now + delay);
      gain.gain.exponentialRampToValueAtTime(0.1, now + delay + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + 0.55);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + delay);
      osc.stop(now + delay + 0.6);
    });
  } catch {
    // audio bloqueado por el navegador: silencio sin romper nada
  }
}

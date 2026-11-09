// Звуковое сопровождение: короткий сигнал при выдаче рекомендаций.
// Используется Web Audio API — внешние звуковые файлы не нужны.
function playBeep(frequency, durationMs) {
  frequency = frequency || 880;
  durationMs = durationMs || 140;
  try {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) { return; }
    var ctx = new Ctx();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + durationMs / 1000);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + durationMs / 1000);
    osc.onended = function () { ctx.close(); };
  } catch (e) {
    // Браузер может блокировать звук до первого действия пользователя — это нормально.
  }
}

// Jenny intro — scenes
// Palette: deep night, coral/peach (matches Jenny mascot), warm cream

const J = {
  night: '#0E0B14',
  nightSoft: '#171320',
  cream: '#FFF6EE',
  creamDim: 'rgba(255, 246, 238, 0.62)',
  coral: '#FF8A7A',
  coralDeep: '#FF6B5B',
  peach: '#FFC4A3',
  pink: '#FFA8C8',
  lilac: '#C9A8FF',
  mint: '#9DE5C7',
  display: '"Instrument Serif", "Times New Roman", serif',
  sans: 'Inter, system-ui, sans-serif',
  mono: '"JetBrains Mono", ui-monospace, monospace',
};

// ── Background grain + radial vignette ─────────────────────────────────────
function NightBG({ children, glow = J.coral, glowOpacity = 0.18 }) {
  return (
    <div style={{
      position: 'absolute', inset: 0,
      background: `radial-gradient(ellipse at 50% 55%, ${hexToRgba(glow, glowOpacity)} 0%, transparent 55%), linear-gradient(180deg, #0E0B14 0%, #0A0810 100%)`,
      overflow: 'hidden',
    }}>
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: 'url("data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><filter id=%22n%22><feTurbulence baseFrequency=%220.9%22 numOctaves=%222%22/></filter><rect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23n)%22 opacity=%220.5%22/></svg>")',
        opacity: 0.07,
        mixBlendMode: 'overlay',
        pointerEvents: 'none',
      }}/>
      {children}
    </div>
  );
}

function hexToRgba(hex, a) {
  const h = hex.replace('#','');
  const r = parseInt(h.slice(0,2),16), g = parseInt(h.slice(2,4),16), b = parseInt(h.slice(4,6),16);
  return `rgba(${r},${g},${b},${a})`;
}

// ── Jenny mascot — animated breathing & squash/stretch ─────────────────────
function Jenny({ x, y, size = 320, mood = 'idle', t = 0, anchor = 'center' }) {
  // breathe = subtle scale + bob
  const breathe = Math.sin(t * 1.6) * 0.025;
  const bob = Math.sin(t * 1.6) * 4;
  let sx = 1 + breathe;
  let sy = 1 - breathe;

  if (mood === 'pop') {
    // entry pop — handled by parent timing
  }
  if (mood === 'wiggle') {
    sx = 1 + Math.sin(t * 6) * 0.04;
    sy = 1 - Math.sin(t * 6) * 0.04;
  }

  const tx = anchor === 'center' ? '-50%' : '0';
  const ty = anchor === 'center' ? '-50%' : '0';

  return (
    <div style={{
      position: 'absolute', left: x, top: y,
      width: size, height: size,
      transform: `translate(${tx}, ${ty}) translateY(${bob}px)`,
      pointerEvents: 'none',
    }}>
      {/* glow halo */}
      <div style={{
        position: 'absolute', inset: '-20%',
        background: `radial-gradient(circle at 50% 50%, ${hexToRgba(J.coral, 0.35)} 0%, transparent 60%)`,
        filter: 'blur(8px)',
      }}/>
      <img src="assets/jenny.png" alt="Jenny" draggable="false"
        style={{
          position: 'relative',
          width: '100%', height: '100%',
          objectFit: 'contain',
          transform: `scale(${sx}, ${sy})`,
          transformOrigin: '50% 90%',
          filter: 'drop-shadow(0 20px 40px rgba(255, 107, 91, 0.35))',
          willChange: 'transform',
        }}/>
    </div>
  );
}

// ── Scene 1: Cold open — Jenny appears ─────────────────────────────────────
function SceneIntro({ start, end }) {
  return (
    <Sprite start={start} end={end}>
      {({ localTime, duration }) => {
        const dur = duration;
        // pulse dot 0–1.0s, jenny pops at 1.0s, "meet jenny" at 1.6s
        const dotIn = clamp(localTime / 0.6, 0, 1);
        const dotOut = clamp((localTime - 0.9) / 0.3, 0, 1);
        const dotScale = Easing.easeOutBack(dotIn) * (1 - dotOut);
        const dotOpacity = (dotIn - dotOut * 1.2);

        // Jenny pop at t=1.0
        const jStart = 1.0;
        const jt = clamp((localTime - jStart) / 0.7, 0, 1);
        const jPop = Easing.easeOutBack(jt);
        const jSize = 360 * jPop;

        // squash on impact
        let sx = 1, sy = 1;
        if (jt < 1 && jt > 0) {
          const impact = clamp((localTime - jStart - 0.5) / 0.2, 0, 1);
          if (impact > 0 && impact < 1) {
            sx = 1 + Math.sin(impact * Math.PI) * 0.15;
            sy = 1 - Math.sin(impact * Math.PI) * 0.15;
          }
        }

        // tagline
        const tagIn = clamp((localTime - 1.7) / 0.6, 0, 1);
        const tagOpacity = Easing.easeOutCubic(tagIn);
        const tagY = (1 - Easing.easeOutCubic(tagIn)) * 16;

        // exit fade
        const fadeOut = clamp((localTime - (dur - 0.5)) / 0.5, 0, 1);
        const sceneOpacity = 1 - fadeOut;

        return (
          <div style={{ position: 'absolute', inset: 0, opacity: sceneOpacity }}>
            <NightBG glow={J.coral} glowOpacity={0.22}>
              {/* pulse dot */}
              <div style={{
                position: 'absolute', left: '50%', top: '50%',
                width: 24, height: 24,
                marginLeft: -12, marginTop: -12,
                background: J.coral,
                borderRadius: '50%',
                boxShadow: `0 0 60px ${J.coral}`,
                opacity: clamp(dotOpacity, 0, 1),
                transform: `scale(${dotScale})`,
              }}/>
              {/* jenny */}
              {jt > 0 && (
                <div style={{
                  position: 'absolute', left: '50%', top: '50%',
                  width: jSize, height: jSize,
                  transform: `translate(-50%, -50%) scale(${sx}, ${sy})`,
                }}>
                  <div style={{
                    position: 'absolute', inset: '-25%',
                    background: `radial-gradient(circle, ${hexToRgba(J.coral, 0.4)} 0%, transparent 60%)`,
                    filter: 'blur(12px)',
                  }}/>
                  <img src="assets/jenny.png" alt="" style={{
                    position: 'relative', width: '100%', height: '100%',
                    objectFit: 'contain',
                    filter: 'drop-shadow(0 30px 60px rgba(255, 107, 91, 0.5))',
                  }}/>
                </div>
              )}
              {/* tagline */}
              <div style={{
                position: 'absolute', left: '50%', top: '76%',
                transform: `translate(-50%, ${tagY}px)`,
                opacity: tagOpacity,
                textAlign: 'center',
              }}>
                <div style={{
                  fontFamily: J.mono, fontSize: 13,
                  letterSpacing: '0.32em', textTransform: 'uppercase',
                  color: J.creamDim, marginBottom: 14,
                }}>— rencontrez —</div>
                <div style={{
                  fontFamily: J.display, fontSize: 96,
                  color: J.cream, lineHeight: 1,
                  letterSpacing: '-0.02em',
                }}>
                  Jenny<span style={{ color: J.coral, fontStyle: 'italic' }}>.</span>
                </div>
              </div>
            </NightBG>
          </div>
        );
      }}
    </Sprite>
  );
}

// ── Scene 2: Overwhelm — messages flood ────────────────────────────────────
const FLOOD_MSGS = [
  { who: 'Sophie', from: 'Instagram', preview: 'Bonjour, est-ce que vous livrez à…', tone: 'pink' },
  { who: 'Marc', from: 'WhatsApp', preview: 'Quel est le prix du modèle XL ?', tone: 'mint' },
  { who: 'Lina', from: 'Email', preview: 'Je voudrais retourner ma commande', tone: 'lilac' },
  { who: 'Karim', from: 'Instagram', preview: 'Toujours dispo en taille M ?', tone: 'pink' },
  { who: 'Anaïs', from: 'WhatsApp', preview: 'Vous êtes ouverts dimanche ?', tone: 'mint' },
  { who: 'Théo', from: 'Email', preview: 'Demande de devis — événement', tone: 'lilac' },
  { who: 'Inès', from: 'Instagram', preview: 'J\'adore !! Vous avez en noir ?', tone: 'pink' },
  { who: 'Hugo', from: 'WhatsApp', preview: 'Mon code promo ne marche pas', tone: 'mint' },
  { who: 'Léa', from: 'Email', preview: 'Question sur la facturation', tone: 'lilac' },
];

function MessageCard({ who, from, preview, tone, opacity = 1, x = 0, y = 0, scale = 1, rotate = 0 }) {
  const accent = tone === 'pink' ? J.pink : tone === 'mint' ? J.mint : J.lilac;
  return (
    <div style={{
      position: 'absolute',
      left: x, top: y,
      transform: `translate(-50%, -50%) scale(${scale}) rotate(${rotate}deg)`,
      opacity,
      width: 360,
      background: 'rgba(255, 246, 238, 0.06)',
      backdropFilter: 'blur(20px)',
      WebkitBackdropFilter: 'blur(20px)',
      border: '1px solid rgba(255, 246, 238, 0.12)',
      borderRadius: 16,
      padding: '14px 16px',
      color: J.cream,
      fontFamily: J.sans,
      boxShadow: '0 16px 40px rgba(0,0,0,0.35)',
      willChange: 'transform, opacity',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <div style={{
          width: 8, height: 8, borderRadius: '50%',
          background: accent, boxShadow: `0 0 10px ${accent}`,
        }}/>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{who}</div>
        <div style={{
          fontFamily: J.mono, fontSize: 10,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: J.creamDim,
          marginLeft: 'auto',
        }}>{from}</div>
      </div>
      <div style={{ fontSize: 13, color: J.creamDim, lineHeight: 1.4 }}>{preview}</div>
    </div>
  );
}

function SceneFlood({ start, end }) {
  // Each message has a target position scattered around screen.
  // They cascade in rapid-fire. Phone in center. Jenny will appear at end.
  const positions = [
    { x: 280, y: 200, r: -8, delay: 0.0 },
    { x: 980, y: 180, r: 6, delay: 0.15 },
    { x: 220, y: 460, r: 5, delay: 0.30 },
    { x: 1020, y: 460, r: -4, delay: 0.45 },
    { x: 200, y: 700, r: -3, delay: 0.60 },
    { x: 1010, y: 700, r: 7, delay: 0.75 },
    { x: 380, y: 140, r: 9, delay: 0.90 },
    { x: 880, y: 720, r: -7, delay: 1.05 },
    { x: 360, y: 760, r: 4, delay: 1.20 },
  ];

  return (
    <Sprite start={start} end={end}>
      {({ localTime, duration }) => {
        const fadeIn = clamp(localTime / 0.4, 0, 1);
        const fadeOut = clamp((localTime - (duration - 0.6)) / 0.6, 0, 1);

        // counter ticking up
        const counterStart = 0.2;
        const counter = Math.floor(clamp((localTime - counterStart) / 1.6, 0, 1) * 247);

        // headline appears at 0.3
        const headIn = clamp((localTime - 0.2) / 0.5, 0, 1);
        const headOpacity = Easing.easeOutCubic(headIn) * (1 - fadeOut);

        return (
          <div style={{ position: 'absolute', inset: 0, opacity: 1 - fadeOut }}>
            <NightBG glow={J.lilac} glowOpacity={0.12}>
              {/* headline */}
              <div style={{
                position: 'absolute', left: '50%', top: 110,
                transform: `translateX(-50%) translateY(${(1-Easing.easeOutCubic(headIn))*12}px)`,
                opacity: headOpacity,
                textAlign: 'center',
                width: 700,
              }}>
                <div style={{
                  fontFamily: J.mono, fontSize: 12,
                  letterSpacing: '0.32em', textTransform: 'uppercase',
                  color: J.creamDim, marginBottom: 12,
                }}>09:14 — un mardi ordinaire</div>
                <div style={{
                  fontFamily: J.display, fontSize: 64,
                  color: J.cream, lineHeight: 1.05,
                  letterSpacing: '-0.02em',
                }}>
                  <span style={{ color: J.coral, fontVariantNumeric: 'tabular-nums' }}>{counter}</span> messages
                  <br/><span style={{ fontStyle: 'italic', color: J.creamDim }}>non lus.</span>
                </div>
              </div>

              {/* flood of cards */}
              {positions.map((p, i) => {
                const m = FLOOD_MSGS[i];
                const t = clamp((localTime - p.delay) / 0.45, 0, 1);
                const eased = Easing.easeOutBack(t);
                const op = clamp(t * 1.3, 0, 1) * (1 - fadeOut);
                const sc = 0.6 + 0.4 * eased;
                if (t <= 0) return null;
                return (
                  <MessageCard key={i}
                    {...m}
                    x={p.x} y={p.y}
                    scale={sc} rotate={p.r}
                    opacity={op}
                  />
                );
              })}

              {/* bottom caption */}
              <div style={{
                position: 'absolute', left: '50%', bottom: 60,
                transform: 'translateX(-50%)',
                opacity: clamp((localTime - 1.8) / 0.5, 0, 1) * (1 - fadeOut),
                fontFamily: J.sans, fontSize: 18,
                color: J.creamDim,
                textAlign: 'center',
              }}>
                Instagram. WhatsApp. Email. <span style={{ color: J.cream }}>Tout en même temps.</span>
              </div>
            </NightBG>
          </div>
        );
      }}
    </Sprite>
  );
}

// ── Scene 3: Jenny replies — chat scene ────────────────────────────────────
function ChatBubble({ who, text, side = 'left', visible, t, color }) {
  const opacity = clamp(t / 0.4, 0, 1);
  const ty = (1 - Easing.easeOutCubic(clamp(t / 0.5, 0, 1))) * 12;
  const sideStyles = side === 'right'
    ? { background: J.coral, color: '#1a0a08', alignSelf: 'flex-end', borderBottomRightRadius: 4 }
    : { background: 'rgba(255,246,238,0.08)', color: J.cream, alignSelf: 'flex-start', borderBottomLeftRadius: 4, border: '1px solid rgba(255,246,238,0.12)' };
  if (!visible) return null;
  return (
    <div style={{
      maxWidth: '78%',
      padding: '12px 16px',
      borderRadius: 18,
      fontFamily: J.sans,
      fontSize: 16,
      lineHeight: 1.4,
      opacity,
      transform: `translateY(${ty}px)`,
      ...sideStyles,
    }}>
      {text}
    </div>
  );
}

function TypingDots({ t }) {
  const phase = (t * 4) % 1;
  const dotOpacity = (i) => {
    const local = (phase + i * 0.2) % 1;
    return 0.3 + 0.7 * Math.max(0, Math.sin(local * Math.PI));
  };
  return (
    <div style={{
      alignSelf: 'flex-start',
      padding: '12px 18px',
      borderRadius: 18,
      borderBottomLeftRadius: 4,
      background: 'rgba(255,246,238,0.06)',
      border: '1px solid rgba(255,246,238,0.1)',
      display: 'flex', gap: 6, alignItems: 'center',
    }}>
      {[0,1,2].map(i => (
        <div key={i} style={{
          width: 7, height: 7, borderRadius: '50%',
          background: J.coral, opacity: dotOpacity(i),
        }}/>
      ))}
    </div>
  );
}

function SceneChat({ start, end }) {
  // Conversation script, with timings
  const script = [
    { at: 0.2, side: 'right', text: 'Bonjour ! Vous livrez à Bordeaux ?' },
    { at: 1.0, side: 'typing' },
    { at: 1.5, side: 'left', text: 'Bonjour Sophie 👋 Oui, livraison gratuite à Bordeaux dès 50€. Vous voulez que je vous aide à finaliser ?' },
    { at: 2.6, side: 'right', text: 'Oui ! Le sac caramel, taille M.' },
    { at: 3.4, side: 'typing' },
    { at: 3.9, side: 'left', text: 'Parfait — il vous reste 3 unités. Je vous envoie le lien de paiement ?' },
  ];

  return (
    <Sprite start={start} end={end}>
      {({ localTime, duration }) => {
        const fadeIn = clamp(localTime / 0.4, 0, 1);
        const fadeOut = clamp((localTime - (duration - 0.6)) / 0.6, 0, 1);

        return (
          <div style={{ position: 'absolute', inset: 0, opacity: fadeIn * (1 - fadeOut) }}>
            <NightBG glow={J.coral} glowOpacity={0.16}>
              {/* Phone frame */}
              <div style={{
                position: 'absolute', left: '50%', top: '50%',
                transform: 'translate(-50%, -50%)',
                width: 420, height: 760,
                background: J.nightSoft,
                borderRadius: 48,
                border: '1px solid rgba(255,246,238,0.1)',
                boxShadow: '0 40px 100px rgba(0,0,0,0.6), inset 0 0 0 6px #050308',
                overflow: 'hidden',
                padding: '60px 24px 24px',
              }}>
                {/* Top: contact */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  paddingBottom: 16,
                  borderBottom: '1px solid rgba(255,246,238,0.08)',
                  marginBottom: 16,
                }}>
                  <div style={{
                    width: 38, height: 38, borderRadius: '50%',
                    background: `linear-gradient(135deg, ${J.coral}, ${J.peach})`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    overflow: 'hidden',
                  }}>
                    <img src="assets/jenny.png" style={{ width: 46, height: 46, objectFit: 'contain', marginTop: 4 }}/>
                  </div>
                  <div>
                    <div style={{ fontFamily: J.sans, fontWeight: 600, fontSize: 15, color: J.cream }}>
                      Jenny <span style={{ color: J.coral, fontWeight: 400 }}>· en ligne</span>
                    </div>
                    <div style={{ fontFamily: J.mono, fontSize: 10, color: J.creamDim, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                      répond pour Maison Lila
                    </div>
                  </div>
                </div>
                {/* Messages stack */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {script.map((m, i) => {
                    const localT = localTime - m.at;
                    if (localT < 0) return null;
                    if (m.side === 'typing') {
                      // typing only shows for 0.5s before next message
                      const next = script[i+1];
                      const cutoff = next ? next.at - m.at : 0.6;
                      if (localT > cutoff) return null;
                      return <TypingDots key={i} t={localT}/>;
                    }
                    return <ChatBubble key={i} side={m.side} text={m.text} t={localT} visible={true}/>;
                  })}
                </div>
              </div>

              {/* Side text */}
              <div style={{
                position: 'absolute', left: 80, top: '50%',
                transform: `translateY(-50%) translateX(${(1-Easing.easeOutCubic(clamp((localTime-0.4)/0.6,0,1)))*-20}px)`,
                opacity: Easing.easeOutCubic(clamp((localTime - 0.4) / 0.6, 0, 1)),
                width: 320,
              }}>
                <div style={{
                  fontFamily: J.mono, fontSize: 12,
                  letterSpacing: '0.32em', textTransform: 'uppercase',
                  color: J.creamDim, marginBottom: 14,
                }}>réponse — 1.4s</div>
                <div style={{
                  fontFamily: J.display, fontSize: 56,
                  color: J.cream, lineHeight: 1.0,
                  letterSpacing: '-0.02em',
                }}>
                  Elle répond,<br/>
                  <span style={{ fontStyle: 'italic', color: J.coral }}>vraiment.</span>
                </div>
                <div style={{
                  fontFamily: J.sans, fontSize: 15,
                  color: J.creamDim, marginTop: 18, lineHeight: 1.5,
                }}>
                  Ton de votre marque. Stock à jour. Lien de paiement direct.
                </div>
              </div>

              {/* Right-side stats */}
              <div style={{
                position: 'absolute', right: 80, top: '50%',
                transform: `translateY(-50%) translateX(${(1-Easing.easeOutCubic(clamp((localTime-0.6)/0.6,0,1)))*20}px)`,
                opacity: Easing.easeOutCubic(clamp((localTime - 0.6) / 0.6, 0, 1)),
                display: 'flex', flexDirection: 'column', gap: 28,
                width: 240,
              }}>
                {[
                  { k: 'Détecte', v: 'l\'intention' },
                  { k: 'Connaît', v: 'votre catalogue' },
                  { k: 'Respecte', v: 'votre voix' },
                ].map((it, i) => (
                  <div key={i} style={{
                    paddingLeft: 16,
                    borderLeft: `2px solid ${J.coral}`,
                  }}>
                    <div style={{ fontFamily: J.mono, fontSize: 11, color: J.creamDim, letterSpacing: '0.16em', textTransform: 'uppercase', marginBottom: 6 }}>{it.k}</div>
                    <div style={{ fontFamily: J.display, fontSize: 28, color: J.cream, fontStyle: 'italic' }}>{it.v}</div>
                  </div>
                ))}
              </div>
            </NightBG>
          </div>
        );
      }}
    </Sprite>
  );
}

// ── Scene 4: Dashboard — counters ──────────────────────────────────────────
function StatCard({ label, value, suffix, accent, delay, localTime, holdT }) {
  const t = clamp((localTime - delay) / 0.6, 0, 1);
  const eased = Easing.easeOutCubic(t);
  const tickT = clamp((localTime - delay - 0.2) / 1.4, 0, 1);
  const displayValue = Math.floor(eased * value > 0 ? Easing.easeOutCubic(tickT) * value : 0);
  return (
    <div style={{
      opacity: t,
      transform: `translateY(${(1 - eased) * 24}px)`,
      background: 'rgba(255,246,238,0.04)',
      border: '1px solid rgba(255,246,238,0.1)',
      borderRadius: 20,
      padding: '24px 28px',
      position: 'relative',
      overflow: 'hidden',
    }}>
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: 3, background: accent,
      }}/>
      <div style={{
        fontFamily: J.mono, fontSize: 11,
        letterSpacing: '0.18em', textTransform: 'uppercase',
        color: J.creamDim, marginBottom: 14,
      }}>{label}</div>
      <div style={{
        fontFamily: J.display, fontSize: 72,
        color: J.cream, lineHeight: 1, letterSpacing: '-0.02em',
        fontVariantNumeric: 'tabular-nums',
      }}>
        {displayValue}<span style={{ color: accent, fontSize: 36 }}>{suffix}</span>
      </div>
    </div>
  );
}

function MiniSparkline({ delay, localTime, accent }) {
  const t = clamp((localTime - delay) / 1.6, 0, 1);
  const eased = Easing.easeOutCubic(t);
  const pts = [10, 18, 14, 28, 24, 38, 32, 50, 56, 72, 68, 84];
  const w = 240, h = 60;
  const max = 100;
  const path = pts.map((p, i) => {
    const x = (i / (pts.length - 1)) * w;
    const y = h - (p / max) * h;
    return `${i === 0 ? 'M' : 'L'}${x},${y}`;
  }).join(' ');
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="sparkfill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.3"/>
          <stop offset="100%" stopColor={accent} stopOpacity="0"/>
        </linearGradient>
      </defs>
      <path d={`${path} L${w},${h} L0,${h} Z`} fill="url(#sparkfill)"
        style={{ opacity: eased }}/>
      <path d={path} stroke={accent} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"
        strokeDasharray="500" strokeDashoffset={500 - eased * 500}/>
    </svg>
  );
}

function SceneDashboard({ start, end }) {
  return (
    <Sprite start={start} end={end}>
      {({ localTime, duration }) => {
        const fadeIn = clamp(localTime / 0.4, 0, 1);
        const fadeOut = clamp((localTime - (duration - 0.6)) / 0.6, 0, 1);

        const headIn = Easing.easeOutCubic(clamp((localTime - 0.1) / 0.5, 0, 1));

        return (
          <div style={{ position: 'absolute', inset: 0, opacity: fadeIn * (1 - fadeOut) }}>
            <NightBG glow={J.coral} glowOpacity={0.10}>
              {/* Header */}
              <div style={{
                position: 'absolute', left: 80, top: 80,
                opacity: headIn,
                transform: `translateY(${(1-headIn) * 12}px)`,
              }}>
                <div style={{
                  fontFamily: J.mono, fontSize: 12,
                  letterSpacing: '0.32em', textTransform: 'uppercase',
                  color: J.creamDim, marginBottom: 12,
                }}>après une semaine avec jenny</div>
                <div style={{
                  fontFamily: J.display, fontSize: 72,
                  color: J.cream, lineHeight: 1.0,
                  letterSpacing: '-0.02em',
                }}>
                  Les chiffres <span style={{ fontStyle: 'italic', color: J.coral }}>parlent.</span>
                </div>
              </div>

              {/* Stat cards row */}
              <div style={{
                position: 'absolute', left: 80, right: 80, top: 320,
                display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24,
              }}>
                <StatCard label="Messages traités" value={1247} suffix="" accent={J.coral} delay={0.5} localTime={localTime}/>
                <StatCard label="Temps de réponse" value={42} suffix="s" accent={J.peach} delay={0.7} localTime={localTime}/>
                <StatCard label="Taux de conversion" value={23} suffix="%" accent={J.mint} delay={0.9} localTime={localTime}/>
              </div>

              {/* Sparkline panel */}
              <div style={{
                position: 'absolute', left: 80, right: 80, bottom: 90,
                opacity: Easing.easeOutCubic(clamp((localTime - 1.1)/0.5, 0, 1)),
                transform: `translateY(${(1-Easing.easeOutCubic(clamp((localTime-1.1)/0.5,0,1)))*16}px)`,
                background: 'rgba(255,246,238,0.04)',
                border: '1px solid rgba(255,246,238,0.1)',
                borderRadius: 20,
                padding: '24px 28px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24,
              }}>
                <div>
                  <div style={{
                    fontFamily: J.mono, fontSize: 11,
                    letterSpacing: '0.18em', textTransform: 'uppercase',
                    color: J.creamDim, marginBottom: 8,
                  }}>volume — 7 derniers jours</div>
                  <div style={{ fontFamily: J.display, fontSize: 32, color: J.cream, fontStyle: 'italic' }}>
                    +<span style={{color: J.coral}}>312%</span> traités sans vous
                  </div>
                </div>
                <MiniSparkline delay={1.2} localTime={localTime} accent={J.coral}/>
              </div>
            </NightBG>
          </div>
        );
      }}
    </Sprite>
  );
}

// ── Scene 5: Final hero ────────────────────────────────────────────────────
function SceneOutro({ start, end }) {
  return (
    <Sprite start={start} end={end}>
      {({ localTime, duration }) => {
        const fadeIn = clamp(localTime / 0.5, 0, 1);
        const eased = Easing.easeOutCubic(fadeIn);

        // Jenny floats up, tagline slides in, wordmark pulses
        const jt = clamp(localTime / 0.8, 0, 1);
        const jenniesY = (1 - Easing.easeOutCubic(jt)) * 40;
        const breathe = Math.sin(localTime * 1.6) * 0.02;
        const bob = Math.sin(localTime * 1.6) * 5;

        const tagT = clamp((localTime - 0.6) / 0.7, 0, 1);
        const tagOp = Easing.easeOutCubic(tagT);
        const tagY = (1 - Easing.easeOutCubic(tagT)) * 20;

        const wmT = clamp((localTime - 1.2) / 0.6, 0, 1);
        const wmOp = Easing.easeOutCubic(wmT);

        return (
          <div style={{ position: 'absolute', inset: 0, opacity: eased }}>
            <NightBG glow={J.coral} glowOpacity={0.28}>
              {/* Jenny */}
              <div style={{
                position: 'absolute', left: '50%', top: '38%',
                width: 260, height: 260,
                transform: `translate(-50%, -50%) translateY(${jenniesY + bob}px) scale(${1+breathe}, ${1-breathe})`,
              }}>
                <div style={{
                  position: 'absolute', inset: '-30%',
                  background: `radial-gradient(circle, ${hexToRgba(J.coral, 0.5)} 0%, transparent 60%)`,
                  filter: 'blur(16px)',
                }}/>
                <img src="assets/jenny.png" alt="" style={{
                  position: 'relative', width: '100%', height: '100%', objectFit: 'contain',
                  filter: 'drop-shadow(0 30px 60px rgba(255, 107, 91, 0.6))',
                }}/>
              </div>

              {/* Tagline */}
              <div style={{
                position: 'absolute', left: '50%', top: '64%',
                transform: `translateX(-50%) translateY(${tagY}px)`,
                opacity: tagOp,
                width: 1000,
                textAlign: 'center',
              }}>
                <div style={{
                  fontFamily: J.display, fontSize: 64,
                  color: J.cream, lineHeight: 1.05,
                  letterSpacing: '-0.02em',
                }}>
                  Transformez chaque message<br/>
                  en <span style={{ fontStyle: 'italic', color: J.coral }}>opportunité.</span>
                </div>
              </div>

              {/* Wordmark + CTA */}
              <div style={{
                position: 'absolute', left: '50%', bottom: 80,
                transform: 'translateX(-50%)',
                opacity: wmOp,
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18,
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  fontFamily: J.mono, fontSize: 12,
                  letterSpacing: '0.4em', textTransform: 'uppercase',
                  color: J.creamDim,
                }}>
                  <div style={{ width: 30, height: 1, background: J.creamDim }}/>
                  jenny.app
                  <div style={{ width: 30, height: 1, background: J.creamDim }}/>
                </div>
              </div>
            </NightBG>
          </div>
        );
      }}
    </Sprite>
  );
}

Object.assign(window, {
  J, hexToRgba,
  Jenny, NightBG,
  SceneIntro, SceneFlood, SceneChat, SceneDashboard, SceneOutro,
});

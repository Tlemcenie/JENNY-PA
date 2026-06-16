// animations.jsx
// Reusable animation starter: Stage, Timeline, Sprite, easing helpers.
// Usage (in an HTML file that loads React + Babel):
//
//   <Stage width={1280} height={720} duration={10} background="#f6f4ef">
//     <MyScene />
//   </Stage>
//
// Inside <Stage>, any child can call useTime() to read the current
// playhead (seconds). Or wrap content in <Sprite start={1} end={4}>...</Sprite>
// to only render during that window -- children receive a `localTime` and
// `progress` via the useSprite() hook.
//
// ─────────────────────────────────────────────────────────────────────────────
// ── Easing functions (hand-rolled, Popmotion-style) ─────────────────────────
// All easings take t ∈ [0,1] and return eased t ∈ [0,1] (may overshoot for back/elastic).
const Easing = {
    linear: (t) => t,
    // Quad
    easeInQuad: (t) => t * t,
    easeOutQuad: (t) => t * (2 - t),
    easeInOutQuad: (t) => (t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t),
    // Cubic
    easeInCubic: (t) => t * t * t,
    easeOutCubic: (t) => (--t) * t * t + 1,
    easeInOutCubic: (t) => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1),
    // Quart
    easeInQuart: (t) => t * t * t * t,
    easeOutQuart: (t) => 1 - (--t) * t * t * t,
    easeInOutQuart: (t) => (t < 0.5 ? 8 * t * t * t * t : 1 - 8 * (--t) * t * t * t),
    // Expo
    easeInExpo: (t) => (t === 0 ? 0 : Math.pow(2, 10 * (t - 1))),
    easeOutExpo: (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)),
    easeInOutExpo: (t) => {
        if (t === 0)
            return 0;
        if (t === 1)
            return 1;
        if (t < 0.5)
            return 0.5 * Math.pow(2, 20 * t - 10);
        return 1 - 0.5 * Math.pow(2, -20 * t + 10);
    },
    // Sine
    easeInSine: (t) => 1 - Math.cos((t * Math.PI) / 2),
    easeOutSine: (t) => Math.sin((t * Math.PI) / 2),
    easeInOutSine: (t) => -(Math.cos(Math.PI * t) - 1) / 2,
    // Back (overshoot)
    easeOutBack: (t) => {
        const c1 = 1.70158, c3 = c1 + 1;
        return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
    },
    easeInBack: (t) => {
        const c1 = 1.70158, c3 = c1 + 1;
        return c3 * t * t * t - c1 * t * t;
    },
    easeInOutBack: (t) => {
        const c1 = 1.70158, c2 = c1 * 1.525;
        return t < 0.5
            ? (Math.pow(2 * t, 2) * ((c2 + 1) * 2 * t - c2)) / 2
            : (Math.pow(2 * t - 2, 2) * ((c2 + 1) * (t * 2 - 2) + c2) + 2) / 2;
    },
    // Elastic
    easeOutElastic: (t) => {
        const c4 = (2 * Math.PI) / 3;
        if (t === 0)
            return 0;
        if (t === 1)
            return 1;
        return Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * c4) + 1;
    },
};
// ── Core interpolation helpers ──────────────────────────────────────────────
// Clamp a value to [min, max]
const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
// interpolate([0, 0.5, 1], [0, 100, 50], ease?) -> fn(t)
// Popmotion-style: linearly maps t across input keyframes to output values,
// with optional easing per segment (single fn or array of fns).
function interpolate(input, output, ease = Easing.linear) {
    return (t) => {
        if (t <= input[0])
            return output[0];
        if (t >= input[input.length - 1])
            return output[output.length - 1];
        for (let i = 0; i < input.length - 1; i++) {
            if (t >= input[i] && t <= input[i + 1]) {
                const span = input[i + 1] - input[i];
                const local = span === 0 ? 0 : (t - input[i]) / span;
                const easeFn = Array.isArray(ease) ? (ease[i] || Easing.linear) : ease;
                const eased = easeFn(local);
                return output[i] + (output[i + 1] - output[i]) * eased;
            }
        }
        return output[output.length - 1];
    };
}
// animate({from, to, start, end, ease})(t) — simpler single-segment tween.
// Returns `from` before `start`, `to` after `end`.
function animate({ from = 0, to = 1, start = 0, end = 1, ease = Easing.easeInOutCubic }) {
    return (t) => {
        if (t <= start)
            return from;
        if (t >= end)
            return to;
        const local = (t - start) / (end - start);
        return from + (to - from) * ease(local);
    };
}
// ── Timeline context ────────────────────────────────────────────────────────
const TimelineContext = React.createContext({ time: 0, duration: 10, playing: false });
const useTime = () => React.useContext(TimelineContext).time;
const useTimeline = () => React.useContext(TimelineContext);
// ── Sprite ──────────────────────────────────────────────────────────────────
// Renders children only when the playhead is inside [start, end]. Provides
// a sub-context with `localTime` (seconds since start) and `progress` (0..1).
//
//   <Sprite start={2} end={5}>
//     {({ localTime, progress }) => <Thing x={progress * 100} />}
//   </Sprite>
//
// Or as a plain wrapper — children can call useSprite() themselves.
const SpriteContext = React.createContext({ localTime: 0, progress: 0, duration: 0 });
const useSprite = () => React.useContext(SpriteContext);
function Sprite({ start = 0, end = Infinity, children, keepMounted = false }) {
    const { time } = useTimeline();
    const visible = time >= start && time <= end;
    if (!visible && !keepMounted)
        return null;
    const duration = end - start;
    const localTime = Math.max(0, time - start);
    const progress = duration > 0 && isFinite(duration)
        ? clamp(localTime / duration, 0, 1)
        : 0;
    const value = { localTime, progress, duration, visible };
    return (React.createElement(SpriteContext.Provider, { value: value }, typeof children === 'function' ? children(value) : children));
}
// ── Sample sprite components ────────────────────────────────────────────────
// TextSprite: fades/slides text in on entry, holds, then fades out on exit.
// Props: text, x, y, size, color, font, entryDur, exitDur, align
function TextSprite({ text, x = 0, y = 0, size = 48, color = '#111', font = 'Inter, system-ui, sans-serif', weight = 600, entryDur = 0.45, exitDur = 0.35, entryEase = Easing.easeOutBack, exitEase = Easing.easeInCubic, align = 'left', letterSpacing = '-0.01em', }) {
    const { localTime, duration } = useSprite();
    const exitStart = Math.max(0, duration - exitDur);
    let opacity = 1;
    let ty = 0;
    if (localTime < entryDur) {
        const t = entryEase(clamp(localTime / entryDur, 0, 1));
        opacity = t;
        ty = (1 - t) * 16;
    }
    else if (localTime > exitStart) {
        const t = exitEase(clamp((localTime - exitStart) / exitDur, 0, 1));
        opacity = 1 - t;
        ty = -t * 8;
    }
    const translateX = align === 'center' ? '-50%' : align === 'right' ? '-100%' : '0';
    return (React.createElement("div", { style: {
            position: 'absolute',
            left: x, top: y,
            transform: `translate(${translateX}, ${ty}px)`,
            opacity,
            fontFamily: font,
            fontSize: size,
            fontWeight: weight,
            color,
            letterSpacing,
            whiteSpace: 'pre',
            lineHeight: 1.1,
            willChange: 'transform, opacity',
        } }, text));
}
// ImageSprite: scales + fades in; optional Ken Burns drift during hold.
function ImageSprite({ src, x = 0, y = 0, width = 400, height = 300, entryDur = 0.6, exitDur = 0.4, kenBurns = false, kenBurnsScale = 1.08, radius = 12, fit = 'cover', placeholder = null, // {label: string} for striped placeholder
 }) {
    const { localTime, duration } = useSprite();
    const exitStart = Math.max(0, duration - exitDur);
    let opacity = 1;
    let scale = 1;
    if (localTime < entryDur) {
        const t = Easing.easeOutCubic(clamp(localTime / entryDur, 0, 1));
        opacity = t;
        scale = 0.96 + 0.04 * t;
    }
    else if (localTime > exitStart) {
        const t = Easing.easeInCubic(clamp((localTime - exitStart) / exitDur, 0, 1));
        opacity = 1 - t;
        scale = (kenBurns ? kenBurnsScale : 1) + 0.02 * t;
    }
    else if (kenBurns) {
        const holdSpan = exitStart - entryDur;
        const holdT = holdSpan > 0 ? (localTime - entryDur) / holdSpan : 0;
        scale = 1 + (kenBurnsScale - 1) * holdT;
    }
    const content = placeholder ? (React.createElement("div", { style: {
            width: '100%', height: '100%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'repeating-linear-gradient(135deg, #e9e6df 0 10px, #dcd8cf 10px 20px)',
            color: '#6b6458',
            fontFamily: 'JetBrains Mono, ui-monospace, monospace',
            fontSize: 13,
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
        } }, placeholder.label || 'image')) : (React.createElement("img", { src: src, alt: "", style: { width: '100%', height: '100%', objectFit: fit, display: 'block' } }));
    return (React.createElement("div", { style: {
            position: 'absolute',
            left: x, top: y,
            width, height,
            opacity,
            transform: `scale(${scale})`,
            transformOrigin: 'center',
            borderRadius: radius,
            overflow: 'hidden',
            willChange: 'transform, opacity',
        } }, content));
}
// RectSprite: simple rectangle that animates position/size/color via props.
// Useful demo primitive — takes a `render` fn for per-frame customization.
function RectSprite({ x = 0, y = 0, width = 100, height = 100, color = '#111', radius = 8, entryDur = 0.4, exitDur = 0.3, render, // optional: (ctx) => style overrides
 }) {
    const spriteCtx = useSprite();
    const { localTime, duration } = spriteCtx;
    const exitStart = Math.max(0, duration - exitDur);
    let opacity = 1;
    let scale = 1;
    if (localTime < entryDur) {
        const t = Easing.easeOutBack(clamp(localTime / entryDur, 0, 1));
        opacity = clamp(localTime / entryDur, 0, 1);
        scale = 0.4 + 0.6 * t;
    }
    else if (localTime > exitStart) {
        const t = Easing.easeInQuad(clamp((localTime - exitStart) / exitDur, 0, 1));
        opacity = 1 - t;
        scale = 1 - 0.15 * t;
    }
    const overrides = render ? render(spriteCtx) : {};
    return (React.createElement("div", { style: {
            position: 'absolute',
            left: x, top: y,
            width, height,
            background: color,
            borderRadius: radius,
            opacity,
            transform: `scale(${scale})`,
            transformOrigin: 'center',
            willChange: 'transform, opacity',
            ...overrides,
        } }));
}
// Mode « incrustation » (?embed=1) : lecture épurée pour la landing —
// aucune barre de lecture, aucun raccourci clavier, démarrage à 0, fond
// transparent. La même page sert donc d'aperçu standalone ET d'embed propre.
const EMBED = (() => {
    try {
        return typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('embed');
    }
    catch {
        return false;
    }
})();
function Stage({ width = 1280, height = 720, duration = 10, background = '#f6f4ef', fps = 60, loop = true, autoplay = true, persistKey = 'animstage', children, }) {
    const [time, setTime] = React.useState(() => {
        if (EMBED)
            return 0;
        try {
            const v = parseFloat(localStorage.getItem(persistKey + ':t') || '0');
            return isFinite(v) ? clamp(v, 0, duration) : 0;
        }
        catch {
            return 0;
        }
    });
    const [playing, setPlaying] = React.useState(autoplay);
    const [hoverTime, setHoverTime] = React.useState(null);
    const [scale, setScale] = React.useState(1);
    const stageRef = React.useRef(null);
    const canvasRef = React.useRef(null);
    const rafRef = React.useRef(null);
    const lastTsRef = React.useRef(null);
    // Persist playhead (jamais en mode incrustation : on repart toujours de 0)
    React.useEffect(() => {
        if (EMBED)
            return;
        try {
            localStorage.setItem(persistKey + ':t', String(time));
        }
        catch { }
    }, [time, persistKey]);
    // Auto-scale to fit viewport
    React.useEffect(() => {
        if (!stageRef.current)
            return;
        const el = stageRef.current;
        const measure = () => {
            const barH = EMBED ? 0 : 44; // playback bar height (masquée en incrustation)
            const s = Math.min(el.clientWidth / width, (el.clientHeight - barH) / height);
            setScale(Math.max(0.05, s));
        };
        measure();
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        window.addEventListener('resize', measure);
        return () => {
            ro.disconnect();
            window.removeEventListener('resize', measure);
        };
    }, [width, height]);
    // Animation loop
    React.useEffect(() => {
        if (!playing) {
            lastTsRef.current = null;
            return;
        }
        const step = (ts) => {
            if (lastTsRef.current == null)
                lastTsRef.current = ts;
            const dt = (ts - lastTsRef.current) / 1000;
            lastTsRef.current = ts;
            setTime((t) => {
                let next = t + dt;
                if (next >= duration) {
                    if (loop)
                        next = next % duration;
                    else {
                        next = duration;
                        setPlaying(false);
                    }
                }
                return next;
            });
            rafRef.current = requestAnimationFrame(step);
        };
        rafRef.current = requestAnimationFrame(step);
        return () => {
            if (rafRef.current)
                cancelAnimationFrame(rafRef.current);
            lastTsRef.current = null;
        };
    }, [playing, duration, loop]);
    // Keyboard: space = play/pause, ← → = seek (désactivé en incrustation)
    React.useEffect(() => {
        if (EMBED)
            return;
        const onKey = (e) => {
            if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'))
                return;
            if (e.code === 'Space') {
                e.preventDefault();
                setPlaying(p => !p);
            }
            else if (e.code === 'ArrowLeft') {
                setTime(t => clamp(t - (e.shiftKey ? 1 : 0.1), 0, duration));
            }
            else if (e.code === 'ArrowRight') {
                setTime(t => clamp(t + (e.shiftKey ? 1 : 0.1), 0, duration));
            }
            else if (e.key === '0' || e.code === 'Home') {
                setTime(0);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [duration]);
    const displayTime = hoverTime != null ? hoverTime : time;
    const ctxValue = React.useMemo(() => ({ time: displayTime, duration, playing, setTime, setPlaying }), [displayTime, duration, playing]);
    return (React.createElement("div", { ref: stageRef, style: {
            position: 'absolute', inset: 0,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center',
            background: EMBED ? 'transparent' : '#0a0a0a',
            fontFamily: 'Inter, system-ui, sans-serif',
        } },
        React.createElement("div", { style: {
                flex: 1,
                width: '100%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                overflow: 'hidden',
                minHeight: 0,
            } },
            React.createElement("div", { ref: canvasRef, style: {
                    width, height,
                    background,
                    position: 'relative',
                    transform: `scale(${scale})`,
                    transformOrigin: 'center',
                    flexShrink: 0,
                    boxShadow: EMBED ? 'none' : '0 20px 60px rgba(0,0,0,0.4)',
                    overflow: 'hidden',
                } },
                React.createElement(TimelineContext.Provider, { value: ctxValue }, children))),
        !EMBED && (React.createElement(PlaybackBar, { time: displayTime, actualTime: time, duration: duration, playing: playing, onPlayPause: () => setPlaying(p => !p), onReset: () => { setTime(0); }, onSeek: (t) => setTime(t), onHover: (t) => setHoverTime(t) }))));
}
// ── Playback bar ────────────────────────────────────────────────────────────
// Play/pause, return-to-begin, scrub track, time display.
// Uses fixed-width time fields so layout doesn't thrash.
function PlaybackBar({ time, duration, playing, onPlayPause, onReset, onSeek, onHover }) {
    const trackRef = React.useRef(null);
    const [dragging, setDragging] = React.useState(false);
    const timeFromEvent = React.useCallback((e) => {
        const rect = trackRef.current.getBoundingClientRect();
        const x = clamp((e.clientX - rect.left) / rect.width, 0, 1);
        return x * duration;
    }, [duration]);
    const onTrackMove = (e) => {
        if (!trackRef.current)
            return;
        const t = timeFromEvent(e);
        if (dragging) {
            onSeek(t);
        }
        else {
            onHover(t);
        }
    };
    const onTrackLeave = () => {
        if (!dragging)
            onHover(null);
    };
    const onTrackDown = (e) => {
        setDragging(true);
        const t = timeFromEvent(e);
        onSeek(t);
        onHover(null);
    };
    React.useEffect(() => {
        if (!dragging)
            return;
        const onUp = () => setDragging(false);
        const onMove = (e) => {
            if (!trackRef.current)
                return;
            const t = timeFromEvent(e);
            onSeek(t);
        };
        window.addEventListener('mouseup', onUp);
        window.addEventListener('mousemove', onMove);
        return () => {
            window.removeEventListener('mouseup', onUp);
            window.removeEventListener('mousemove', onMove);
        };
    }, [dragging, timeFromEvent, onSeek]);
    const pct = duration > 0 ? (time / duration) * 100 : 0;
    const fmt = (t) => {
        const total = Math.max(0, t);
        const m = Math.floor(total / 60);
        const s = Math.floor(total % 60);
        const cs = Math.floor((total * 100) % 100);
        return `${String(m).padStart(1, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
    };
    const mono = 'JetBrains Mono, ui-monospace, SFMono-Regular, monospace';
    return (React.createElement("div", { style: {
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '8px 16px',
            background: 'rgba(20,20,20,0.92)',
            borderTop: '1px solid rgba(255,255,255,0.08)',
            width: '100%',
            maxWidth: 680,
            alignSelf: 'center',
            borderRadius: 8,
            color: '#f6f4ef',
            fontFamily: 'Inter, system-ui, sans-serif',
            userSelect: 'none',
            flexShrink: 0,
        } },
        React.createElement(IconButton, { onClick: onReset, title: "Return to start (0)" },
            React.createElement("svg", { width: "14", height: "14", viewBox: "0 0 14 14", fill: "none" },
                React.createElement("path", { d: "M3 2v10M12 2L5 7l7 5V2z", stroke: "currentColor", strokeWidth: "1.5", strokeLinejoin: "round", strokeLinecap: "round" }))),
        React.createElement(IconButton, { onClick: onPlayPause, title: "Play/pause (space)" }, playing ? (React.createElement("svg", { width: "14", height: "14", viewBox: "0 0 14 14", fill: "none" },
            React.createElement("rect", { x: "3", y: "2", width: "3", height: "10", fill: "currentColor" }),
            React.createElement("rect", { x: "8", y: "2", width: "3", height: "10", fill: "currentColor" }))) : (React.createElement("svg", { width: "14", height: "14", viewBox: "0 0 14 14", fill: "none" },
            React.createElement("path", { d: "M3 2l9 5-9 5V2z", fill: "currentColor" })))),
        React.createElement("div", { style: {
                fontFamily: mono,
                fontSize: 12,
                fontVariantNumeric: 'tabular-nums',
                width: 64, textAlign: 'right',
                color: '#f6f4ef',
            } }, fmt(time)),
        React.createElement("div", { ref: trackRef, onMouseMove: onTrackMove, onMouseLeave: onTrackLeave, onMouseDown: onTrackDown, style: {
                flex: 1,
                height: 22,
                position: 'relative',
                cursor: 'pointer',
                display: 'flex', alignItems: 'center',
            } },
            React.createElement("div", { style: {
                    position: 'absolute',
                    left: 0, right: 0, height: 4,
                    background: 'rgba(255,255,255,0.12)',
                    borderRadius: 2,
                } }),
            React.createElement("div", { style: {
                    position: 'absolute',
                    left: 0, width: `${pct}%`, height: 4,
                    background: 'oklch(72% 0.12 250)',
                    borderRadius: 2,
                } }),
            React.createElement("div", { style: {
                    position: 'absolute',
                    left: `${pct}%`, top: '50%',
                    width: 12, height: 12,
                    marginLeft: -6, marginTop: -6,
                    background: '#fff',
                    borderRadius: 6,
                    boxShadow: '0 2px 4px rgba(0,0,0,0.4)',
                } })),
        React.createElement("div", { style: {
                fontFamily: mono,
                fontSize: 12,
                fontVariantNumeric: 'tabular-nums',
                width: 64, textAlign: 'left',
                color: 'rgba(246,244,239,0.55)',
            } }, fmt(duration))));
}
function IconButton({ children, onClick, title }) {
    const [hover, setHover] = React.useState(false);
    return (React.createElement("button", { onClick: onClick, title: title, onMouseEnter: () => setHover(true), onMouseLeave: () => setHover(false), style: {
            width: 28, height: 28,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: hover ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 6,
            color: '#f6f4ef',
            cursor: 'pointer',
            padding: 0,
            transition: 'background 120ms',
        } }, children));
}
Object.assign(window, {
    Easing, interpolate, animate, clamp,
    TimelineContext, useTime, useTimeline,
    Sprite, SpriteContext, useSprite,
    TextSprite, ImageSprite, RectSprite,
    Stage, PlaybackBar,
});
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
    return (React.createElement("div", { style: {
            position: 'absolute', inset: 0,
            background: `radial-gradient(ellipse at 50% 55%, ${hexToRgba(glow, glowOpacity)} 0%, transparent 55%), linear-gradient(180deg, #0E0B14 0%, #0A0810 100%)`,
            overflow: 'hidden',
        } },
        React.createElement("div", { style: {
                position: 'absolute', inset: 0,
                backgroundImage: 'url("data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><filter id=%22n%22><feTurbulence baseFrequency=%220.9%22 numOctaves=%222%22/></filter><rect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23n)%22 opacity=%220.5%22/></svg>")',
                opacity: 0.07,
                mixBlendMode: 'overlay',
                pointerEvents: 'none',
            } }),
        children));
}
function hexToRgba(hex, a) {
    const h = hex.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
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
    return (React.createElement("div", { style: {
            position: 'absolute', left: x, top: y,
            width: size, height: size,
            transform: `translate(${tx}, ${ty}) translateY(${bob}px)`,
            pointerEvents: 'none',
        } },
        React.createElement("div", { style: {
                position: 'absolute', inset: '-20%',
                background: `radial-gradient(circle at 50% 50%, ${hexToRgba(J.coral, 0.35)} 0%, transparent 60%)`,
                filter: 'blur(8px)',
            } }),
        React.createElement("img", { src: "assets/jenny.png", alt: "Jenny", draggable: "false", style: {
                position: 'relative',
                width: '100%', height: '100%',
                objectFit: 'contain',
                transform: `scale(${sx}, ${sy})`,
                transformOrigin: '50% 90%',
                filter: 'drop-shadow(0 20px 40px rgba(255, 107, 91, 0.35))',
                willChange: 'transform',
            } })));
}
// ── Scene 1: Cold open — Jenny appears ─────────────────────────────────────
function SceneIntro({ start, end }) {
    return (React.createElement(Sprite, { start: start, end: end }, ({ localTime, duration }) => {
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
        return (React.createElement("div", { style: { position: 'absolute', inset: 0, opacity: sceneOpacity } },
            React.createElement(NightBG, { glow: J.coral, glowOpacity: 0.22 },
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', top: '50%',
                        width: 24, height: 24,
                        marginLeft: -12, marginTop: -12,
                        background: J.coral,
                        borderRadius: '50%',
                        boxShadow: `0 0 60px ${J.coral}`,
                        opacity: clamp(dotOpacity, 0, 1),
                        transform: `scale(${dotScale})`,
                    } }),
                jt > 0 && (React.createElement("div", { style: {
                        position: 'absolute', left: '50%', top: '50%',
                        width: jSize, height: jSize,
                        transform: `translate(-50%, -50%) scale(${sx}, ${sy})`,
                    } },
                    React.createElement("div", { style: {
                            position: 'absolute', inset: '-25%',
                            background: `radial-gradient(circle, ${hexToRgba(J.coral, 0.4)} 0%, transparent 60%)`,
                            filter: 'blur(12px)',
                        } }),
                    React.createElement("img", { src: "assets/jenny.png", alt: "", style: {
                            position: 'relative', width: '100%', height: '100%',
                            objectFit: 'contain',
                            filter: 'drop-shadow(0 30px 60px rgba(255, 107, 91, 0.5))',
                        } }))),
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', top: '76%',
                        transform: `translate(-50%, ${tagY}px)`,
                        opacity: tagOpacity,
                        textAlign: 'center',
                    } },
                    React.createElement("div", { style: {
                            fontFamily: J.mono, fontSize: 13,
                            letterSpacing: '0.32em', textTransform: 'uppercase',
                            color: J.creamDim, marginBottom: 14,
                        } }, "\u2014 rencontrez \u2014"),
                    React.createElement("div", { style: {
                            fontFamily: J.display, fontSize: 96,
                            color: J.cream, lineHeight: 1,
                            letterSpacing: '-0.02em',
                        } },
                        "Jenny",
                        React.createElement("span", { style: { color: J.coral, fontStyle: 'italic' } }, "."))))));
    }));
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
    return (React.createElement("div", { style: {
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
        } },
        React.createElement("div", { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 } },
            React.createElement("div", { style: {
                    width: 8, height: 8, borderRadius: '50%',
                    background: accent, boxShadow: `0 0 10px ${accent}`,
                } }),
            React.createElement("div", { style: { fontWeight: 600, fontSize: 14 } }, who),
            React.createElement("div", { style: {
                    fontFamily: J.mono, fontSize: 10,
                    letterSpacing: '0.1em', textTransform: 'uppercase',
                    color: J.creamDim,
                    marginLeft: 'auto',
                } }, from)),
        React.createElement("div", { style: { fontSize: 13, color: J.creamDim, lineHeight: 1.4 } }, preview)));
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
    return (React.createElement(Sprite, { start: start, end: end }, ({ localTime, duration }) => {
        const fadeIn = clamp(localTime / 0.4, 0, 1);
        const fadeOut = clamp((localTime - (duration - 0.6)) / 0.6, 0, 1);
        // counter ticking up
        const counterStart = 0.2;
        const counter = Math.floor(clamp((localTime - counterStart) / 1.6, 0, 1) * 247);
        // headline appears at 0.3
        const headIn = clamp((localTime - 0.2) / 0.5, 0, 1);
        const headOpacity = Easing.easeOutCubic(headIn) * (1 - fadeOut);
        return (React.createElement("div", { style: { position: 'absolute', inset: 0, opacity: 1 - fadeOut } },
            React.createElement(NightBG, { glow: J.lilac, glowOpacity: 0.12 },
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', top: 110,
                        transform: `translateX(-50%) translateY(${(1 - Easing.easeOutCubic(headIn)) * 12}px)`,
                        opacity: headOpacity,
                        textAlign: 'center',
                        width: 700,
                    } },
                    React.createElement("div", { style: {
                            fontFamily: J.mono, fontSize: 12,
                            letterSpacing: '0.32em', textTransform: 'uppercase',
                            color: J.creamDim, marginBottom: 12,
                        } }, "09:14 \u2014 un mardi ordinaire"),
                    React.createElement("div", { style: {
                            fontFamily: J.display, fontSize: 64,
                            color: J.cream, lineHeight: 1.05,
                            letterSpacing: '-0.02em',
                        } },
                        React.createElement("span", { style: { color: J.coral, fontVariantNumeric: 'tabular-nums' } }, counter),
                        " messages",
                        React.createElement("br", null),
                        React.createElement("span", { style: { fontStyle: 'italic', color: J.creamDim } }, "non lus."))),
                positions.map((p, i) => {
                    const m = FLOOD_MSGS[i];
                    const t = clamp((localTime - p.delay) / 0.45, 0, 1);
                    const eased = Easing.easeOutBack(t);
                    const op = clamp(t * 1.3, 0, 1) * (1 - fadeOut);
                    const sc = 0.6 + 0.4 * eased;
                    if (t <= 0)
                        return null;
                    return (React.createElement(MessageCard, { key: i, ...m, x: p.x, y: p.y, scale: sc, rotate: p.r, opacity: op }));
                }),
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', bottom: 60,
                        transform: 'translateX(-50%)',
                        opacity: clamp((localTime - 1.8) / 0.5, 0, 1) * (1 - fadeOut),
                        fontFamily: J.sans, fontSize: 18,
                        color: J.creamDim,
                        textAlign: 'center',
                    } },
                    "Instagram. WhatsApp. Email. ",
                    React.createElement("span", { style: { color: J.cream } }, "Tout en m\u00EAme temps.")))));
    }));
}
// ── Scene 3: Jenny replies — chat scene ────────────────────────────────────
function ChatBubble({ who, text, side = 'left', visible, t, color }) {
    const opacity = clamp(t / 0.4, 0, 1);
    const ty = (1 - Easing.easeOutCubic(clamp(t / 0.5, 0, 1))) * 12;
    const sideStyles = side === 'right'
        ? { background: J.coral, color: '#1a0a08', alignSelf: 'flex-end', borderBottomRightRadius: 4 }
        : { background: 'rgba(255,246,238,0.08)', color: J.cream, alignSelf: 'flex-start', borderBottomLeftRadius: 4, border: '1px solid rgba(255,246,238,0.12)' };
    if (!visible)
        return null;
    return (React.createElement("div", { style: {
            maxWidth: '78%',
            padding: '12px 16px',
            borderRadius: 18,
            fontFamily: J.sans,
            fontSize: 16,
            lineHeight: 1.4,
            opacity,
            transform: `translateY(${ty}px)`,
            ...sideStyles,
        } }, text));
}
function TypingDots({ t }) {
    const phase = (t * 4) % 1;
    const dotOpacity = (i) => {
        const local = (phase + i * 0.2) % 1;
        return 0.3 + 0.7 * Math.max(0, Math.sin(local * Math.PI));
    };
    return (React.createElement("div", { style: {
            alignSelf: 'flex-start',
            padding: '12px 18px',
            borderRadius: 18,
            borderBottomLeftRadius: 4,
            background: 'rgba(255,246,238,0.06)',
            border: '1px solid rgba(255,246,238,0.1)',
            display: 'flex', gap: 6, alignItems: 'center',
        } }, [0, 1, 2].map(i => (React.createElement("div", { key: i, style: {
            width: 7, height: 7, borderRadius: '50%',
            background: J.coral, opacity: dotOpacity(i),
        } })))));
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
    return (React.createElement(Sprite, { start: start, end: end }, ({ localTime, duration }) => {
        const fadeIn = clamp(localTime / 0.4, 0, 1);
        const fadeOut = clamp((localTime - (duration - 0.6)) / 0.6, 0, 1);
        return (React.createElement("div", { style: { position: 'absolute', inset: 0, opacity: fadeIn * (1 - fadeOut) } },
            React.createElement(NightBG, { glow: J.coral, glowOpacity: 0.16 },
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', top: '50%',
                        transform: 'translate(-50%, -50%)',
                        width: 420, height: 760,
                        background: J.nightSoft,
                        borderRadius: 48,
                        border: '1px solid rgba(255,246,238,0.1)',
                        boxShadow: '0 40px 100px rgba(0,0,0,0.6), inset 0 0 0 6px #050308',
                        overflow: 'hidden',
                        padding: '60px 24px 24px',
                    } },
                    React.createElement("div", { style: {
                            display: 'flex', alignItems: 'center', gap: 12,
                            paddingBottom: 16,
                            borderBottom: '1px solid rgba(255,246,238,0.08)',
                            marginBottom: 16,
                        } },
                        React.createElement("div", { style: {
                                width: 38, height: 38, borderRadius: '50%',
                                background: `linear-gradient(135deg, ${J.coral}, ${J.peach})`,
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                overflow: 'hidden',
                            } },
                            React.createElement("img", { src: "assets/jenny.png", style: { width: 46, height: 46, objectFit: 'contain', marginTop: 4 } })),
                        React.createElement("div", null,
                            React.createElement("div", { style: { fontFamily: J.sans, fontWeight: 600, fontSize: 15, color: J.cream } },
                                "Jenny ",
                                React.createElement("span", { style: { color: J.coral, fontWeight: 400 } }, "\u00B7 en ligne")),
                            React.createElement("div", { style: { fontFamily: J.mono, fontSize: 10, color: J.creamDim, letterSpacing: '0.1em', textTransform: 'uppercase' } }, "r\u00E9pond pour Maison Lila"))),
                    React.createElement("div", { style: { display: 'flex', flexDirection: 'column', gap: 10 } }, script.map((m, i) => {
                        const localT = localTime - m.at;
                        if (localT < 0)
                            return null;
                        if (m.side === 'typing') {
                            // typing only shows for 0.5s before next message
                            const next = script[i + 1];
                            const cutoff = next ? next.at - m.at : 0.6;
                            if (localT > cutoff)
                                return null;
                            return React.createElement(TypingDots, { key: i, t: localT });
                        }
                        return React.createElement(ChatBubble, { key: i, side: m.side, text: m.text, t: localT, visible: true });
                    }))),
                React.createElement("div", { style: {
                        position: 'absolute', left: 80, top: '50%',
                        transform: `translateY(-50%) translateX(${(1 - Easing.easeOutCubic(clamp((localTime - 0.4) / 0.6, 0, 1))) * -20}px)`,
                        opacity: Easing.easeOutCubic(clamp((localTime - 0.4) / 0.6, 0, 1)),
                        width: 320,
                    } },
                    React.createElement("div", { style: {
                            fontFamily: J.mono, fontSize: 12,
                            letterSpacing: '0.32em', textTransform: 'uppercase',
                            color: J.creamDim, marginBottom: 14,
                        } }, "r\u00E9ponse \u2014 1.4s"),
                    React.createElement("div", { style: {
                            fontFamily: J.display, fontSize: 56,
                            color: J.cream, lineHeight: 1.0,
                            letterSpacing: '-0.02em',
                        } },
                        "Elle r\u00E9pond,",
                        React.createElement("br", null),
                        React.createElement("span", { style: { fontStyle: 'italic', color: J.coral } }, "vraiment.")),
                    React.createElement("div", { style: {
                            fontFamily: J.sans, fontSize: 15,
                            color: J.creamDim, marginTop: 18, lineHeight: 1.5,
                        } }, "Ton de votre marque. Stock \u00E0 jour. Lien de paiement direct.")),
                React.createElement("div", { style: {
                        position: 'absolute', right: 80, top: '50%',
                        transform: `translateY(-50%) translateX(${(1 - Easing.easeOutCubic(clamp((localTime - 0.6) / 0.6, 0, 1))) * 20}px)`,
                        opacity: Easing.easeOutCubic(clamp((localTime - 0.6) / 0.6, 0, 1)),
                        display: 'flex', flexDirection: 'column', gap: 28,
                        width: 240,
                    } }, [
                    { k: 'Détecte', v: 'l\'intention' },
                    { k: 'Connaît', v: 'votre catalogue' },
                    { k: 'Respecte', v: 'votre voix' },
                ].map((it, i) => (React.createElement("div", { key: i, style: {
                        paddingLeft: 16,
                        borderLeft: `2px solid ${J.coral}`,
                    } },
                    React.createElement("div", { style: { fontFamily: J.mono, fontSize: 11, color: J.creamDim, letterSpacing: '0.16em', textTransform: 'uppercase', marginBottom: 6 } }, it.k),
                    React.createElement("div", { style: { fontFamily: J.display, fontSize: 28, color: J.cream, fontStyle: 'italic' } }, it.v))))))));
    }));
}
// ── Scene 4: Dashboard — counters ──────────────────────────────────────────
function StatCard({ label, value, suffix, accent, delay, localTime, holdT }) {
    const t = clamp((localTime - delay) / 0.6, 0, 1);
    const eased = Easing.easeOutCubic(t);
    const tickT = clamp((localTime - delay - 0.2) / 1.4, 0, 1);
    const displayValue = Math.floor(eased * value > 0 ? Easing.easeOutCubic(tickT) * value : 0);
    return (React.createElement("div", { style: {
            opacity: t,
            transform: `translateY(${(1 - eased) * 24}px)`,
            background: 'rgba(255,246,238,0.04)',
            border: '1px solid rgba(255,246,238,0.1)',
            borderRadius: 20,
            padding: '24px 28px',
            position: 'relative',
            overflow: 'hidden',
        } },
        React.createElement("div", { style: {
                position: 'absolute', left: 0, top: 0, bottom: 0,
                width: 3, background: accent,
            } }),
        React.createElement("div", { style: {
                fontFamily: J.mono, fontSize: 11,
                letterSpacing: '0.18em', textTransform: 'uppercase',
                color: J.creamDim, marginBottom: 14,
            } }, label),
        React.createElement("div", { style: {
                fontFamily: J.display, fontSize: 72,
                color: J.cream, lineHeight: 1, letterSpacing: '-0.02em',
                fontVariantNumeric: 'tabular-nums',
            } },
            displayValue,
            React.createElement("span", { style: { color: accent, fontSize: 36 } }, suffix))));
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
    return (React.createElement("svg", { width: w, height: h, style: { display: 'block' } },
        React.createElement("defs", null,
            React.createElement("linearGradient", { id: "sparkfill", x1: "0", x2: "0", y1: "0", y2: "1" },
                React.createElement("stop", { offset: "0%", stopColor: accent, stopOpacity: "0.3" }),
                React.createElement("stop", { offset: "100%", stopColor: accent, stopOpacity: "0" }))),
        React.createElement("path", { d: `${path} L${w},${h} L0,${h} Z`, fill: "url(#sparkfill)", style: { opacity: eased } }),
        React.createElement("path", { d: path, stroke: accent, strokeWidth: "2", fill: "none", strokeLinecap: "round", strokeLinejoin: "round", strokeDasharray: "500", strokeDashoffset: 500 - eased * 500 })));
}
function SceneDashboard({ start, end }) {
    return (React.createElement(Sprite, { start: start, end: end }, ({ localTime, duration }) => {
        const fadeIn = clamp(localTime / 0.4, 0, 1);
        const fadeOut = clamp((localTime - (duration - 0.6)) / 0.6, 0, 1);
        const headIn = Easing.easeOutCubic(clamp((localTime - 0.1) / 0.5, 0, 1));
        return (React.createElement("div", { style: { position: 'absolute', inset: 0, opacity: fadeIn * (1 - fadeOut) } },
            React.createElement(NightBG, { glow: J.coral, glowOpacity: 0.10 },
                React.createElement("div", { style: {
                        position: 'absolute', left: 80, top: 80,
                        opacity: headIn,
                        transform: `translateY(${(1 - headIn) * 12}px)`,
                    } },
                    React.createElement("div", { style: {
                            fontFamily: J.mono, fontSize: 12,
                            letterSpacing: '0.32em', textTransform: 'uppercase',
                            color: J.creamDim, marginBottom: 12,
                        } }, "apr\u00E8s une semaine avec jenny"),
                    React.createElement("div", { style: {
                            fontFamily: J.display, fontSize: 72,
                            color: J.cream, lineHeight: 1.0,
                            letterSpacing: '-0.02em',
                        } },
                        "Les chiffres ",
                        React.createElement("span", { style: { fontStyle: 'italic', color: J.coral } }, "parlent."))),
                React.createElement("div", { style: {
                        position: 'absolute', left: 80, right: 80, top: 320,
                        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24,
                    } },
                    React.createElement(StatCard, { label: "Messages trait\u00E9s", value: 1247, suffix: "", accent: J.coral, delay: 0.5, localTime: localTime }),
                    React.createElement(StatCard, { label: "Temps de r\u00E9ponse", value: 42, suffix: "s", accent: J.peach, delay: 0.7, localTime: localTime }),
                    React.createElement(StatCard, { label: "Taux de conversion", value: 23, suffix: "%", accent: J.mint, delay: 0.9, localTime: localTime })),
                React.createElement("div", { style: {
                        position: 'absolute', left: 80, right: 80, bottom: 90,
                        opacity: Easing.easeOutCubic(clamp((localTime - 1.1) / 0.5, 0, 1)),
                        transform: `translateY(${(1 - Easing.easeOutCubic(clamp((localTime - 1.1) / 0.5, 0, 1))) * 16}px)`,
                        background: 'rgba(255,246,238,0.04)',
                        border: '1px solid rgba(255,246,238,0.1)',
                        borderRadius: 20,
                        padding: '24px 28px',
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24,
                    } },
                    React.createElement("div", null,
                        React.createElement("div", { style: {
                                fontFamily: J.mono, fontSize: 11,
                                letterSpacing: '0.18em', textTransform: 'uppercase',
                                color: J.creamDim, marginBottom: 8,
                            } }, "volume \u2014 7 derniers jours"),
                        React.createElement("div", { style: { fontFamily: J.display, fontSize: 32, color: J.cream, fontStyle: 'italic' } },
                            "+",
                            React.createElement("span", { style: { color: J.coral } }, "312%"),
                            " trait\u00E9s sans vous")),
                    React.createElement(MiniSparkline, { delay: 1.2, localTime: localTime, accent: J.coral })))));
    }));
}
// ── Scene 5: Final hero ────────────────────────────────────────────────────
function SceneOutro({ start, end }) {
    return (React.createElement(Sprite, { start: start, end: end }, ({ localTime, duration }) => {
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
        return (React.createElement("div", { style: { position: 'absolute', inset: 0, opacity: eased } },
            React.createElement(NightBG, { glow: J.coral, glowOpacity: 0.28 },
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', top: '38%',
                        width: 260, height: 260,
                        transform: `translate(-50%, -50%) translateY(${jenniesY + bob}px) scale(${1 + breathe}, ${1 - breathe})`,
                    } },
                    React.createElement("div", { style: {
                            position: 'absolute', inset: '-30%',
                            background: `radial-gradient(circle, ${hexToRgba(J.coral, 0.5)} 0%, transparent 60%)`,
                            filter: 'blur(16px)',
                        } }),
                    React.createElement("img", { src: "assets/jenny.png", alt: "", style: {
                            position: 'relative', width: '100%', height: '100%', objectFit: 'contain',
                            filter: 'drop-shadow(0 30px 60px rgba(255, 107, 91, 0.6))',
                        } })),
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', top: '64%',
                        transform: `translateX(-50%) translateY(${tagY}px)`,
                        opacity: tagOp,
                        width: 1000,
                        textAlign: 'center',
                    } },
                    React.createElement("div", { style: {
                            fontFamily: J.display, fontSize: 64,
                            color: J.cream, lineHeight: 1.05,
                            letterSpacing: '-0.02em',
                        } },
                        "Transformez chaque message",
                        React.createElement("br", null),
                        "en ",
                        React.createElement("span", { style: { fontStyle: 'italic', color: J.coral } }, "opportunit\u00E9."))),
                React.createElement("div", { style: {
                        position: 'absolute', left: '50%', bottom: 80,
                        transform: 'translateX(-50%)',
                        opacity: wmOp,
                        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18,
                    } },
                    React.createElement("div", { style: {
                            display: 'flex', alignItems: 'center', gap: 10,
                            fontFamily: J.mono, fontSize: 12,
                            letterSpacing: '0.4em', textTransform: 'uppercase',
                            color: J.creamDim,
                        } },
                        React.createElement("div", { style: { width: 30, height: 1, background: J.creamDim } }),
                        "jenny.app",
                        React.createElement("div", { style: { width: 30, height: 1, background: J.creamDim } }))))));
    }));
}
Object.assign(window, {
    J, hexToRgba,
    Jenny, NightBG,
    SceneIntro, SceneFlood, SceneChat, SceneDashboard, SceneOutro,
});
// Jenny intro — root app
const TOTAL = 22;
// Scene timings (start, end)
const TIMING = {
    intro: [0, 4.5],
    flood: [4.3, 9.0],
    chat: [8.8, 14.5],
    dashboard: [14.3, 18.5],
    outro: [18.3, 22.0],
};
function TimestampLabel() {
    const t = useTime();
    React.useEffect(() => {
        const root = document.getElementById('video-root');
        if (root)
            root.setAttribute('data-screen-label', `t=${Math.floor(t)}s`);
    }, [Math.floor(t)]);
    return null;
}
function App() {
    return (React.createElement("div", { id: "video-root", "data-screen-label": "t=0s" },
        React.createElement(Stage, { width: 1280, height: 720, duration: TOTAL, background: "#0E0B14", persistKey: "jenny-intro" },
            React.createElement(TimestampLabel, null),
            React.createElement(SceneIntro, { start: TIMING.intro[0], end: TIMING.intro[1] }),
            React.createElement(SceneFlood, { start: TIMING.flood[0], end: TIMING.flood[1] }),
            React.createElement(SceneChat, { start: TIMING.chat[0], end: TIMING.chat[1] }),
            React.createElement(SceneDashboard, { start: TIMING.dashboard[0], end: TIMING.dashboard[1] }),
            React.createElement(SceneOutro, { start: TIMING.outro[0], end: TIMING.outro[1] }))));
}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App, null));

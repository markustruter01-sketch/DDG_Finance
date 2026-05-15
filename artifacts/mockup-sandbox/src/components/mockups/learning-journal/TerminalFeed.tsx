import { useEffect, useRef, useState } from "react";

type Line = { type: "prompt" | "code" | "output" | "comment" | "header" | "gap"; text: string };

const allLines: Line[] = [
  { type: "header",  text: "╔══════════════════════════════════════════════════╗" },
  { type: "header",  text: "║   PYTHON LEARNING JOURNAL · Digital Dynamics     ║" },
  { type: "header",  text: "║   Session: 2026-05-15 · Operator: Navigator      ║" },
  { type: "header",  text: "╚══════════════════════════════════════════════════╝" },
  { type: "gap",     text: "" },
  { type: "comment", text: "# ── ENTRY 042: Generators & Lazy Evaluation ───────" },
  { type: "prompt",  text: ">>> " },
  { type: "code",    text: "def fibonacci():" },
  { type: "code",    text: "...     a, b = 0, 1" },
  { type: "code",    text: "...     while True:" },
  { type: "code",    text: "...         yield a" },
  { type: "code",    text: "...         a, b = b, a + b" },
  { type: "prompt",  text: ">>> " },
  { type: "code",    text: "fib = fibonacci()" },
  { type: "prompt",  text: ">>> " },
  { type: "code",    text: "[next(fib) for _ in range(8)]" },
  { type: "output",  text: "[0, 1, 1, 2, 3, 5, 8, 13]" },
  { type: "gap",     text: "" },
  { type: "comment", text: "# KEY INSIGHT: generators don't run until iterated." },
  { type: "comment", text: "# Like a bot in standby — no CPU until market open." },
  { type: "gap",     text: "" },
  { type: "comment", text: "# ── ENTRY 043: Decorator Pattern ───────────────────" },
  { type: "prompt",  text: ">>> " },
  { type: "code",    text: "def log_call(fn):" },
  { type: "code",    text: "...     @wraps(fn)" },
  { type: "code",    text: "...     def wrapper(*args, **kw):" },
  { type: "code",    text: "...         print(f'CALL {fn.__name__}')" },
  { type: "code",    text: "...         return fn(*args, **kw)" },
  { type: "code",    text: "...     return wrapper" },
  { type: "prompt",  text: ">>> " },
  { type: "code",    text: "@log_call" },
  { type: "code",    text: "def execute_trade(symbol, qty): ..." },
  { type: "prompt",  text: ">>> " },
  { type: "code",    text: "execute_trade('AAPL', 10)" },
  { type: "output",  text: "CALL execute_trade" },
  { type: "output",  text: "ORDER PLACED: BUY 10x AAPL @ $178.42" },
  { type: "gap",     text: "" },
  { type: "comment", text: "# Decorators = reusable behaviour injection. Clean." },
];

const COLOR: Record<Line["type"], string> = {
  header:  "#22d3ee",
  prompt:  "#a78bfa",
  code:    "#e2e8f0",
  output:  "#34d399",
  comment: "#475569",
  gap:     "transparent",
};

export function TerminalFeed() {
  const [shown, setShown] = useState(0);
  const [blink, setBlink] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (shown < allLines.length) {
      const delay = allLines[shown].type === "gap" ? 80
        : allLines[shown].type === "header" ? 40
        : allLines[shown].type === "comment" ? 120
        : 90;
      const t = setTimeout(() => setShown(s => s + 1), delay);
      return () => clearTimeout(t);
    }
  }, [shown]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [shown]);

  useEffect(() => {
    const t = setInterval(() => setBlink(b => !b), 530);
    return () => clearInterval(t);
  }, []);

  return (
    <div
      className="min-h-screen w-full p-6 overflow-y-auto"
      style={{
        background: "#0a0a0a",
        fontFamily: "'Fira Code', 'Courier New', Courier, monospace",
      }}
    >
      <div className="flex items-center gap-2 mb-4">
        <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57" }} />
        <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#ffbd2e" }} />
        <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840" }} />
        <span style={{ color: "#475569", fontSize: 11, marginLeft: 8 }}>python-journal — bash — 80×40</span>
      </div>

      <div style={{ fontSize: 13, lineHeight: 1.8 }}>
        {allLines.slice(0, shown).map((line, i) => (
          <div key={i} style={{ display: "flex" }}>
            {line.type === "prompt" ? (
              <span style={{ color: "#a78bfa", userSelect: "none" }}>{">>> "}</span>
            ) : null}
            <span style={{ color: COLOR[line.type] }}>
              {line.type === "prompt" ? "" : line.text}
            </span>
          </div>
        ))}
        {shown < allLines.length && (
          <div style={{ display: "flex", alignItems: "center" }}>
            <span style={{ color: "#a78bfa" }}>{">>> "}</span>
            <span
              style={{
                display: "inline-block",
                width: 8,
                height: 16,
                background: "#22d3ee",
                opacity: blink ? 1 : 0,
                transition: "opacity 0.1s",
                marginLeft: 1,
                verticalAlign: "middle",
              }}
            />
          </div>
        )}
        {shown >= allLines.length && (
          <div style={{ display: "flex", alignItems: "center", marginTop: 4 }}>
            <span style={{ color: "#a78bfa" }}>{">>> "}</span>
            <span
              style={{
                display: "inline-block",
                width: 8,
                height: 16,
                background: "#22d3ee",
                opacity: blink ? 1 : 0,
                transition: "opacity 0.1s",
                marginLeft: 1,
                verticalAlign: "middle",
              }}
            />
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

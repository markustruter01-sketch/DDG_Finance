import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface AnimatedValueProps {
  value: string;
  className?: string;
}

function FlipDigit({ digit, flipKey }: { digit: string; flipKey: number }) {
  return (
    <span className="inline-block relative overflow-hidden" style={{ width: "0.6em" }}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={flipKey}
          initial={{ rotateX: -90, opacity: 0, y: "-0.15em" }}
          animate={{ rotateX: 0, opacity: 1, y: 0 }}
          exit={{ rotateX: 90, opacity: 0, y: "0.15em" }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="inline-block"
          style={{ transformOrigin: "center center", backfaceVisibility: "hidden" }}
        >
          {digit}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

export function AnimatedValue({ value, className = "" }: AnimatedValueProps) {
  const [chars, setChars] = useState<{ char: string; flipKey: number }[]>(() =>
    value.split("").map((c) => ({ char: c, flipKey: 0 }))
  );
  const valueRef = useRef(value);
  const charsRef = useRef(chars);
  const counterRef = useRef(1);

  const updateFromValue = useCallback((newVal: string) => {
    const newChars = newVal.split("");
    const prev = charsRef.current;
    const updated = newChars.map((c, i) => {
      const old = prev[i];
      if (old && old.char === c) return old;
      return { char: c, flipKey: counterRef.current++ };
    });
    charsRef.current = updated;
    setChars(updated);
  }, []);

  useEffect(() => {
    if (value !== valueRef.current) {
      valueRef.current = value;
      updateFromValue(value);
    }
  }, [value, updateFromValue]);

  useEffect(() => {
    const interval = setInterval(() => {
      const current = charsRef.current;
      if (current.length === 0) return;

      const digitIndices: number[] = [];
      for (let i = 0; i < current.length; i++) {
        if (/\d/.test(current[i].char)) digitIndices.push(i);
      }
      if (digitIndices.length === 0) return;

      const pickCount = Math.min(
        1 + Math.floor(Math.random() * 2),
        digitIndices.length
      );
      const shuffled = [...digitIndices].sort(() => Math.random() - 0.5);
      const toFlip = new Set(shuffled.slice(0, pickCount));

      const updated = current.map((entry, i) => {
        if (!toFlip.has(i)) return entry;
        const d = parseInt(entry.char, 10);
        const jitter = Math.random() < 0.5 ? 1 : -1;
        const newDigit = ((d + jitter + 10) % 10).toString();
        return { char: newDigit, flipKey: counterRef.current++ };
      });

      charsRef.current = updated;
      setChars(updated);

      setTimeout(() => {
        const real = valueRef.current.split("");
        const restored = charsRef.current.map((entry, i) => {
          const correct = real[i];
          if (!correct || entry.char === correct) return entry;
          return { char: correct, flipKey: counterRef.current++ };
        });
        charsRef.current = restored;
        setChars(restored);
      }, 800);
    }, 3000 + Math.random() * 1500);

    return () => clearInterval(interval);
  }, []);

  return (
    <span className={`inline-flex overflow-hidden relative ${className}`} style={{ perspective: "200px" }}>
      {chars.map((c, i) => (
        /\d/.test(c.char) ? (
          <FlipDigit key={i} digit={c.char} flipKey={c.flipKey} />
        ) : (
          <span key={i} className="inline-block">{c.char}</span>
        )
      ))}
    </span>
  );
}

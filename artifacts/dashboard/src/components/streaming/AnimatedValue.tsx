import { useEffect, useRef, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface AnimatedValueProps {
  value: string;
  className?: string;
}

function FlipChar({ char, prevChar }: { char: string; prevChar: string }) {
  const isDigit = /\d/.test(char);
  const changed = char !== prevChar;

  if (!isDigit || !changed) {
    return <span className="inline-block">{char}</span>;
  }

  return (
    <span className="inline-block relative overflow-hidden" style={{ width: "0.6em" }}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={char}
          initial={{ rotateX: -90, opacity: 0, y: "-0.15em" }}
          animate={{ rotateX: 0, opacity: 1, y: 0 }}
          exit={{ rotateX: 90, opacity: 0, y: "0.15em" }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          className="inline-block"
          style={{ transformOrigin: "center center", backfaceVisibility: "hidden" }}
        >
          {char}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

export function AnimatedValue({ value, className = "" }: AnimatedValueProps) {
  const [displayValue, setDisplayValue] = useState(value);
  const [prevValue, setPrevValue] = useState(value);
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      setDisplayValue(value);
      setPrevValue(value);
      return;
    }

    if (value !== displayValue) {
      setPrevValue(displayValue);
      setDisplayValue(value);
    }
  }, [value]);

  const chars = useMemo(() => {
    const curr = displayValue.split("");
    const prev = prevValue.padEnd(curr.length).split("");

    const prevAligned = prevValue.split("");
    while (prevAligned.length < curr.length) prevAligned.unshift(" ");
    while (prevAligned.length > curr.length) prevAligned.shift();

    return curr.map((c, i) => ({
      char: c,
      prevChar: prevAligned[i] ?? " ",
      key: `${i}-${c}`,
    }));
  }, [displayValue, prevValue]);

  return (
    <span className={`inline-flex overflow-hidden relative ${className}`} style={{ perspective: "200px" }}>
      {chars.map((c, i) => (
        <FlipChar key={i} char={c.char} prevChar={c.prevChar} />
      ))}
    </span>
  );
}

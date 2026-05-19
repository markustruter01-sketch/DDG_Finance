export type TradePulseEvent = {
  type: "win" | "loss";
  botName: string;
};

type Listener = (event: TradePulseEvent) => void;

const listeners = new Set<Listener>();

export function emitTradePulse(event: TradePulseEvent) {
  for (const fn of listeners) fn(event);
}

export function onTradePulse(fn: Listener): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

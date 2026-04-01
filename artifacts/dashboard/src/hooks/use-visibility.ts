import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { focusManager } from "@tanstack/react-query";

const VisibilityContext = createContext<boolean>(true);

export function useDocumentVisibility(): boolean {
  return useContext(VisibilityContext);
}

export { VisibilityContext };

let _listenerInstalled = false;

export function installVisibilityListener() {
  if (_listenerInstalled) return;
  _listenerInstalled = true;

  focusManager.setEventListener((handleFocus) => {
    const onVisChange = () => {
      handleFocus(document.visibilityState === "visible");
    };
    document.addEventListener("visibilitychange", onVisChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisChange);
    };
  });
}

export function useVisibilityProvider(): boolean {
  const [isVisible, setIsVisible] = useState(
    typeof document !== "undefined" ? document.visibilityState === "visible" : true
  );

  useEffect(() => {
    installVisibilityListener();

    const handler = () => setIsVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, []);

  return isVisible;
}

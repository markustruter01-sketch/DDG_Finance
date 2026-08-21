import { useLocation } from "wouter";
import { LayoutDashboard, Radio } from "lucide-react";

const NAV_ITEMS = [
  {
    id:    "home",
    label: "Home",
    path:  "/",
    icon:  LayoutDashboard,
    color: "#3b82f6",
    pulse: false,
  },
  {
    id:    "stream",
    label: "Stream",
    path:  "/stream",
    icon:  Radio,
    color: "#f43f5e",
    pulse: false,
  },
];

export function GlobalNav() {
  const [location, navigate] = useLocation();
  const isHomeRoute = location === "/" || location === "" || location === "/home";

  return (
    <nav
      className={`fixed bottom-5 left-1/2 z-[9999] pointer-events-none ${isHomeRoute ? "home-global-nav" : ""}`}
      style={{ transform: "translateX(-50%)" }}
    >
      <div
        className="flex items-center gap-2.5 pointer-events-auto"
      >
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.path === "/"
              ? location === "/" || location === "" || location === "/home"
              : location === item.path || location.startsWith(item.path + "/");

          return (
            <button
              key={item.id}
              onClick={() => navigate(item.path)}
              className="relative flex flex-col items-center justify-center rounded-2xl transition-all duration-300 select-none"
              style={{
                minWidth: 62,
                paddingTop: 10,
                paddingBottom: 10,
                paddingLeft: 14,
                paddingRight: 14,
                ...(isActive
                  ? {
                      background: `linear-gradient(135deg, ${item.color}26, ${item.color}12)`,
                      border: `1px solid ${item.color}55`,
                      boxShadow: `0 4px 24px ${item.color}30, 0 0 0 1px ${item.color}15, inset 0 1px 0 ${item.color}20`,
                      transform: "translateY(-1px) scale(1.04)",
                    }
                  : {
                      background: isHomeRoute ? "rgba(255,255,255,0.12)" : "rgba(15, 23, 42, 0.80)",
                      border: isHomeRoute ? "1px solid rgba(100,116,139,0.20)" : "1px solid rgba(255,255,255,0.075)",
                      boxShadow: isHomeRoute ? "0 8px 24px rgba(15,23,42,0.16)" : "0 4px 16px rgba(0,0,0,0.50), 0 1px 0 rgba(255,255,255,0.04) inset",
                    }),
              }}
            >
              <span className="relative">
                <Icon
                  className="h-5 w-5"
                  style={{ color: isActive ? item.color : isHomeRoute ? "rgba(71,85,105,0.75)" : "rgba(148,163,184,0.65)" }}
                />
                {item.pulse && (
                  <span
                    className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full"
                    style={{
                      background: item.color,
                      boxShadow: `0 0 5px ${item.color}`,
                      animation: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
                    }}
                  />
                )}
              </span>
              <span
                className="text-[9px] font-black tracking-widest uppercase mt-1"
                style={{
                  color: isActive ? item.color : isHomeRoute ? "rgba(71,85,105,0.85)" : "rgba(100,116,139,0.85)",
                }}
              >
                {item.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

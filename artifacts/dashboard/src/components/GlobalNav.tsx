import { useLocation } from "wouter";
import { FlaskConical, LayoutGrid, Radio, ShieldAlert } from "lucide-react";
import "@/styles/brand.css";

// Brand dock (guide p10): tiles 84 x 62, radius 16, active = accent outline,
// every icon paired with a mono label. Outline icons, 1.8 px stroke.
const NAV_ITEMS = [
  { id: "home", label: "Home", path: "/", icon: LayoutGrid },
  { id: "stream", label: "Stream", path: "/stream", icon: Radio },
  { id: "bench", label: "Bench", path: "/bench", icon: FlaskConical },
  { id: "controls", label: "Controls", path: "/controls", icon: ShieldAlert },
];

export function GlobalNav() {
  const [location, navigate] = useLocation();
  return (
    <nav className="ddg-dock ddg-glass" aria-label="Main">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const active = item.path === "/"
          ? location === "/" || location === "" || location === "/home"
          : location === item.path || location.startsWith(item.path + "/");
        return (
          <button
            key={item.id}
            type="button"
            className="ddg-dock-tile"
            data-testid={`button-global-nav-${item.id}`}
            aria-current={active ? "page" : undefined}
            onClick={() => navigate(item.path)}
          >
            <Icon size={22} strokeWidth={1.8} aria-hidden="true" />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

import React, { useState } from "react";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";

// Shared standard UI components for the dashboard

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("rounded-xl border bg-card text-card-foreground shadow-lg shadow-black/20", className)} {...props} />
  )
);
Card.displayName = "Card";

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex flex-col space-y-1.5 p-6", className)} {...props} />
  )
);
CardHeader.displayName = "CardHeader";

export const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref} className={cn("text-lg font-semibold leading-none tracking-tight", className)} {...props} />
  )
);
CardTitle.displayName = "CardTitle";

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
  )
);
CardContent.displayName = "CardContent";

export const Badge = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { variant?: "default" | "success" | "danger" | "warning" | "outline" }>(
  ({ className, variant = "default", ...props }, ref) => {
    const variants = {
      default: "bg-primary/20 text-primary border-primary/30",
      success: "bg-success/20 text-success border-success/30",
      danger: "bg-destructive/20 text-destructive border-destructive/30",
      warning: "bg-amber-500/20 text-amber-500 border-amber-500/30",
      outline: "border-border text-foreground",
    };
    return (
      <div ref={ref} className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors", variants[variant], className)} {...props} />
    );
  }
);
Badge.displayName = "Badge";

export const Button = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "danger" | "success" | "outline" | "ghost", size?: "default" | "sm" | "lg" }>(
  ({ className, variant = "default", size = "default", disabled, ...props }, ref) => {
    const variants = {
      default: "bg-primary text-primary-foreground hover:bg-primary/90 shadow-[0_0_15px_rgba(59,130,246,0.2)]",
      danger: "bg-destructive text-destructive-foreground hover:bg-destructive/90 shadow-[0_0_15px_rgba(244,63,94,0.2)]",
      success: "bg-success text-success-foreground hover:bg-success/90 shadow-[0_0_15px_rgba(16,185,129,0.2)]",
      outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
      ghost: "hover:bg-accent hover:text-accent-foreground",
    };
    const sizes = {
      default: "h-10 px-4 py-2",
      sm: "h-9 rounded-md px-3",
      lg: "h-11 rounded-md px-8",
    };
    return (
      <button
        ref={ref}
        disabled={disabled}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          disabled ? "opacity-50 cursor-not-allowed transform-none" : "active:scale-[0.98]",
          variants[variant],
          sizes[size],
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export function Modal({ isOpen, onClose, title, children }: { isOpen: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2"
          >
            <div className="mx-4 overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
              <div className="flex items-center justify-between border-b border-border p-4">
                <h2 className="text-lg font-semibold">{title}</h2>
                <button onClick={onClose} className="rounded-full p-1 hover:bg-white/10 transition-colors">
                  <X className="h-5 w-5 text-muted-foreground" />
                </button>
              </div>
              <div className="p-6">{children}</div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export function PnlText({ value, isAbs = false }: { value: number | null | undefined, isAbs?: boolean }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  const formatted = isAbs ? value.toFixed(2) : (value / 100).toFixed(4); // just generic raw text handling if needed, better to use formatter
  
  if (value > 0) return <span className="text-success terminal-text text-glow-success">+{value.toFixed(2)}{!isAbs && '%'}</span>;
  if (value < 0) return <span className="text-destructive terminal-text text-glow-danger">{value.toFixed(2)}{!isAbs && '%'}</span>;
  return <span className="text-muted-foreground terminal-text">0.00{!isAbs && '%'}</span>;
}

export function PnlValue({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  const formatted = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Math.abs(value));
  if (value > 0) return <span className="text-success terminal-text text-glow-success">+{formatted}</span>;
  if (value < 0) return <span className="text-destructive terminal-text text-glow-danger">-{formatted}</span>;
  return <span className="text-muted-foreground terminal-text">{formatted}</span>;
}

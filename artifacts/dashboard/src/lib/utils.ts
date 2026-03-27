import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { format } from "date-fns";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val);
}

export function formatPercent(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
    signDisplay: "always"
  }).format(val / 100);
}

export function formatPercentAbs(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  }).format(val);
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    return format(new Date(dateStr), "MMM dd, yyyy HH:mm");
  } catch (e) {
    return dateStr;
  }
}

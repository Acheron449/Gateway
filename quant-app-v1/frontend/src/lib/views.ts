export type View =
  | "overview"
  | "scanner"
  | "markets"
  | "calendar"
  | "strategies"
  | "backtests"
  | "paper-trading"
  | "journal"
  | "risk"
  | "divergence"
  | "settings";

export interface ViewDef {
  id: View;
  label: string;
  icon: string;
  group: "workspace" | "myWork" | "settings";
}

export const VIEWS: ViewDef[] = [
  { id: "overview", label: "Overview", icon: "🏠", group: "workspace" },
  { id: "scanner", label: "Scanner", icon: "🔍", group: "workspace" },
  { id: "markets", label: "Markets", icon: "📈", group: "workspace" },
  { id: "calendar", label: "Calendar", icon: "📅", group: "workspace" },
  { id: "strategies", label: "Strategies", icon: "🎯", group: "myWork" },
  { id: "backtests", label: "Backtests", icon: "📊", group: "myWork" },
  { id: "paper-trading", label: "Paper Trading", icon: "📝", group: "myWork" },
  { id: "journal", label: "Journal", icon: "📓", group: "myWork" },
  { id: "risk", label: "Risk", icon: "⚠️", group: "myWork" },
  { id: "divergence", label: "Divergence", icon: "📉", group: "myWork" },
  { id: "settings", label: "Providers", icon: "🔧", group: "settings" },
];

export const VIEW_IDS = VIEWS.map((v) => v.id);

export function isView(value: string | undefined | null): value is View {
  return !!value && (VIEW_IDS as string[]).includes(value);
}

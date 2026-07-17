import {
  Activity,
  BarChart3,
  BedDouble,
  BookOpen,
  CalendarDays,
  ClipboardCheck,
  Database,
  Dumbbell,
  Flag,
  HeartPulse,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  Moon,
  Pill,
  Plug,
  Plus,
  Repeat,
  Settings,
  Sparkles,
  Utensils,
  Wallet,
} from "lucide-react";

export type NavItem = {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
};

/** Mobile: five loop-stage destinations; Log is centre-emphasised. */
export const MOBILE_NAV: NavItem[] = [
  { key: "today", label: "Today", href: "/", icon: LayoutDashboard },
  { key: "plan", label: "Plan", href: "/plan", icon: CalendarDays },
  { key: "log", label: "Log", href: "/log", icon: Plus },
  { key: "insights", label: "Insights", href: "/insights", icon: BarChart3 },
  { key: "more", label: "More", href: "/more", icon: Repeat },
];

/** Desktop: grouped, collapsible sidebar (brief §4). */
export type NavGroup = { label: string; items: NavItem[] };

export const SIDEBAR_GROUPS: NavGroup[] = [
  {
    label: "Daily",
    items: [
      { key: "today", label: "Today", href: "/", icon: LayoutDashboard },
      { key: "plan", label: "Schedule", href: "/plan", icon: CalendarDays },
      { key: "checkin", label: "Check-in", href: "/log?flow=checkin", icon: ClipboardCheck },
    ],
  },
  {
    label: "Plan & record",
    items: [
      { key: "training", label: "Training", href: "/training", icon: Dumbbell },
      { key: "nutrition", label: "Nutrition", href: "/nutrition", icon: Utensils },
      { key: "habits", label: "Habits", href: "/plan/habits", icon: Repeat },
      { key: "journal", label: "Journal", href: "/mind", icon: BookOpen },
      { key: "goals", label: "Goals", href: "/plan/goals", icon: Flag },
    ],
  },
  {
    label: "Understand",
    items: [
      { key: "health", label: "Health", href: "/health", icon: HeartPulse },
      { key: "recovery", label: "Recovery", href: "/recovery", icon: Activity },
      { key: "insights", label: "Insights", href: "/insights", icon: BarChart3 },
      { key: "reports", label: "Reports", href: "/insights/reports", icon: BookOpen },
    ],
  },
  {
    label: "System",
    items: [
      { key: "integrations", label: "Integrations", href: "/integrations", icon: Plug },
      { key: "data", label: "Data sources", href: "/data", icon: Database },
      { key: "settings", label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

/** More-sheet on mobile: everything not in the five persistent tabs. */
export const MORE_ITEMS: NavItem[] = [
  { key: "health", label: "Health", href: "/health", icon: HeartPulse },
  { key: "recovery", label: "Recovery", href: "/recovery", icon: Activity },
  { key: "training", label: "Training", href: "/training", icon: Dumbbell },
  { key: "nutrition", label: "Nutrition", href: "/nutrition", icon: Utensils },
  { key: "mind", label: "Mind", href: "/mind", icon: Moon },
  { key: "medication", label: "Medication", href: "/medication", icon: Pill },
  { key: "habits", label: "Habits", href: "/plan/habits", icon: Repeat },
  { key: "goals", label: "Goals", href: "/plan/goals", icon: Flag },
  { key: "sleep", label: "Sleep", href: "/insights/metric/sleep", icon: BedDouble },
  { key: "money", label: "Money", href: "/money", icon: Wallet },
  { key: "tasks", label: "Tasks", href: "/tasks", icon: ListChecks },
  { key: "reports", label: "Reports", href: "/insights/reports", icon: BookOpen },
  { key: "integrations", label: "Integrations", href: "/integrations", icon: Plug },
  { key: "data", label: "Data sources", href: "/data", icon: Database },
  { key: "settings", label: "Settings", href: "/settings", icon: Settings },
];

export const BRAND_ICON = Sparkles;

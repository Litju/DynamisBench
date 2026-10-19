/**
 * The status badge: the shell's one piece of tone-carrying chrome.
 *
 * Four tones, because the workbench's states are one of four things — nothing to report, on
 * the way, working, or broken — and a component that could render an arbitrary colour would
 * be a component that eventually made two broken states look different for no reason. The
 * tone is chosen by the runtime-state model, not by the caller's taste.
 */

import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "./cn";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-slate-100 text-slate-600",
        pending: "bg-amber-50 text-amber-700",
        ready: "bg-emerald-50 text-emerald-700",
        danger: "bg-rose-50 text-rose-700",
      },
    },
    defaultVariants: {
      tone: "neutral",
    },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

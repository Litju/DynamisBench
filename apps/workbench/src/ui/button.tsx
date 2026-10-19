/**
 * The button primitive: a small, source-owned component, not a component library.
 *
 * Composed the way shadcn-style primitives are — sizes from CVA, `cn` for overrides, and
 * Radix's `Slot` so a button can *be* a link without either component knowing about the
 * other. `asChild` is the only reason Radix is here at all: the shell needs navigation that
 * is a real anchor with a button's styling, and an anchor inside a button is the alternative
 * nobody wants.
 *
 * One dimension, with the two sizes the shell actually renders. A `variant` dimension
 * arrives with the second visual weight, not before it: an unused variant is a colour nobody
 * chose.
 */

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "./cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium text-slate-600 transition-colors " +
    "hover:bg-slate-100 hover:text-slate-900 " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
    "disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      size: {
        /** A full-width, left-aligned row: what the navigation rail's items are. */
        nav: "h-9 w-full justify-start px-2",
        /** A square control: an icon with nothing beside it. */
        icon: "h-8 w-8",
      },
    },
    defaultVariants: {
      size: "nav",
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render as the child element, keeping this component's styling. */
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, size, asChild = false, ...props },
  ref,
) {
  const Component = asChild ? Slot : "button";
  return (
    <Component ref={ref} className={cn(buttonVariants({ size }), className)} {...props} />
  );
});

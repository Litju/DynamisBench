/**
 * The button primitive: a small, source-owned component, not a component library.
 *
 * Composed the way shadcn-style primitives are — variants from CVA, `cn` for overrides, and
 * Radix's `Slot` so a button can *be* a link without either component knowing about the
 * other. `asChild` is the only reason Radix is here at all: the shell needs navigation that
 * is a real anchor and a real button's styling, and rendering a button inside an anchor is
 * the alternative nobody wants.
 */

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "./cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
    "disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        outline: "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
      },
      size: {
        sm: "h-8 px-3",
        icon: "h-8 w-8",
        nav: "h-9 w-full justify-start px-2",
      },
    },
    defaultVariants: {
      variant: "ghost",
      size: "sm",
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
  { className, variant, size, asChild = false, ...props },
  ref,
) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
});

/**
 * The workbench shell: header, navigation rail, and the region routes render into.
 *
 * Restrained on purpose. This milestone establishes where things go and what the application
 * looks like while it decides whether it has an API; the three-pane authority UI, the
 * artifact inspector and every scientific view arrive with the milestone that owns them, and
 * a shell that guessed at their layout now would be a shell that had to be undone.
 *
 * The rail is the one piece of UI-local state ([`useUiStore`]) and Lucide is the one icon
 * set: the icons here are status and navigation glyphs, not scientific ones.
 */

import { Link } from "@tanstack/react-router";
import { Activity, FolderOpen, House, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import { useUiStore } from "../store/ui";
import { Button } from "../ui/button";
import { cn } from "../ui/cn";
import { RuntimeStatus } from "./runtime-status";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <Activity aria-hidden className="h-5 w-5 text-slate-400" />
        <div className="min-w-0">
          <span className="block text-sm font-semibold tracking-tight">DynamisBench</span>
          <span className="block truncate text-xs text-slate-500">
            Human-movement VVUQ workbench
          </span>
        </div>
        <RuntimeStatus className="ml-auto" />
      </header>
      <div className="flex flex-1 items-stretch">
        <NavigationRail />
        <main className="min-w-0 flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

function NavigationRail() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);

  return (
    <nav
      aria-label="Workbench"
      data-collapsed={collapsed}
      className={cn(
        "flex shrink-0 flex-col gap-1 border-r border-slate-200 bg-white p-2 transition-[width]",
        collapsed ? "w-14" : "w-56",
      )}
    >
      <Button
        type="button"
        size="icon"
        onClick={toggleSidebar}
        aria-expanded={!collapsed}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        className={cn("mb-1 text-slate-400", collapsed ? "self-center" : "self-end")}
      >
        {collapsed ? (
          <PanelLeftOpen aria-hidden className="h-4 w-4" />
        ) : (
          <PanelLeftClose aria-hidden className="h-4 w-4" />
        )}
      </Button>

      <RailItem to="/" icon={House} label="Overview" collapsed={collapsed} />

      {/* Not a route yet, and not a dead link either: the workspace explorer is the next
          milestone's surface, and a disabled entry states that rather than pretending. */}
      <div
        aria-disabled="true"
        title="The workspace explorer arrives with the next milestone."
        data-nav-item="workspaces"
        className={cn(
          "flex h-9 cursor-not-allowed items-center gap-2 rounded-md px-2 text-sm font-medium text-slate-300",
          collapsed && "justify-center px-0",
        )}
      >
        <FolderOpen aria-hidden className="h-4 w-4 shrink-0" />
        {!collapsed && <span className="truncate">Workspaces</span>}
      </div>
    </nav>
  );
}

/**
 * One rail entry: a real link, styled by the button primitive, carrying its own icon.
 *
 * The active state travels as a data attribute rather than as a second class list, so the
 * link never competes with the button's own sizing and one `data-[active=true]:` utility
 * decides the highlight.
 */
function RailItem({
  to,
  icon: Icon,
  label,
  collapsed,
}: {
  to: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  label: string;
  collapsed: boolean;
}) {
  return (
    <Button
      asChild
      size="nav"
      className={cn(
        "data-[active=true]:bg-slate-100 data-[active=true]:text-slate-900",
        collapsed && "justify-center px-0",
      )}
    >
      <Link
        to={to}
        activeProps={{ "data-active": "true" }}
        aria-label={collapsed ? label : undefined}
      >
        <Icon aria-hidden className="h-4 w-4 shrink-0" />
        {!collapsed && <span className="truncate">{label}</span>}
      </Link>
    </Button>
  );
}

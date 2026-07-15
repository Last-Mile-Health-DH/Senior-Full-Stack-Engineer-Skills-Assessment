"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { EXTERNAL_NAV, INTERNAL_NAV, isActivePath } from "../lib/chatCore";

const MENU_ID = "primary-navigation";

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  // The menu is an overlay below 1024px, so Escape must dismiss it.
  useEffect(() => {
    if (!menuOpen) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  // A route change means the user picked a link; the overlay must not linger.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <button
          type="button"
          className="menu-toggle"
          aria-expanded={menuOpen}
          aria-controls={MENU_ID}
          aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="menu-icon" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="menu-toggle-text">Menu</span>
        </button>
        <p className="app-topbar-title">Ask your documents</p>
      </header>

      {menuOpen ? (
        // Click-outside-to-close is a redundant affordance: the toggle and Escape already
        // close the menu. Exposing it as a button would put a second control with the same
        // label in the accessibility tree, so it stays hidden from assistive tech.
        <div className="menu-scrim" aria-hidden="true" onClick={() => setMenuOpen(false)} />
      ) : null}

      <aside id={MENU_ID} className={`app-sidebar${menuOpen ? " is-open" : ""}`}>
        <div className="sidebar-brand">
          <p className="app-kicker">Last Mile Health</p>
          <h1>Ask your documents</h1>
          <p className="sidebar-blurb">
            Upload a document, ask a question, and get an answer that shows the page it came
            from.
          </p>
        </div>

        <nav className="sidebar-nav" aria-label="Primary">
          <p className="nav-heading" id="nav-workspace">
            Workspace
          </p>
          <ul aria-labelledby="nav-workspace">
            {INTERNAL_NAV.map((item) => {
              const active = isActivePath(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={`nav-link${active ? " is-active" : ""}`}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setMenuOpen(false)}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>

          <p className="nav-heading" id="nav-services">
            Other views
          </p>
          <ul aria-labelledby="nav-services">
            {EXTERNAL_NAV.map((item) => (
              <li key={item.href}>
                {/* External services never claim active state: this app cannot know
                    whether the user is currently looking at them. */}
                <a
                  href={item.href}
                  className="nav-link is-external"
                  target="_blank"
                  rel="noreferrer"
                >
                  {item.label}
                  <span aria-hidden="true">↗</span>
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <p className="sidebar-note">
          There is a second chat view at port 8000. Both views give the same answers and show
          the same sources — use whichever you prefer.
        </p>
      </aside>

      <main className="app-main">{children}</main>
    </div>
  );
}

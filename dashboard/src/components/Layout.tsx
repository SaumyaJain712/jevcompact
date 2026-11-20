import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

const KEY = "jevcompact.lastSession";

function readLast(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

const LastSession = createContext<{ last: string | null; setLast: (id: string | null) => void }>({
  last: null,
  setLast: () => undefined,
});

export function useLastSession() {
  return useContext(LastSession);
}

export function Logo() {
  return (
    <NavLink to="/sessions" className="logo" aria-label="JevCompact home">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill="#fff" />
        <path d="M9 10h14M9 16h9M9 22h5" stroke="#293786" strokeWidth="3" strokeLinecap="round" />
      </svg>
      JevCompact
    </NavLink>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const [last, setLastState] = useState<string | null>(readLast);
  const loc = useLocation();
  const setLast = (id: string | null) => {
    setLastState(id);
    try {
      if (id) localStorage.setItem(KEY, id);
      else localStorage.removeItem(KEY);
    } catch {
      /* storage unavailable */
    }
  };
  useEffect(() => {
    const m = loc.pathname.match(/^\/sessions\/([^/]+)/);
    if (m && m[1] !== last) setLast(m[1]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc.pathname]);

  const onReview = /^\/sessions\/[^/]+$/.test(loc.pathname);
  const onCompare = /^\/sessions\/[^/]+\/compare$/.test(loc.pathname);
  const sessionLink = (label: string, to: string, active: boolean) =>
    last ? (
      <NavLink to={to} className={() => (active ? "active" : "")}>
        {label}
      </NavLink>
    ) : (
      <span className="disabled" title="Open a session first" aria-disabled="true">
        {label}
      </span>
    );

  return (
    <LastSession.Provider value={{ last, setLast }}>
      <div className="app">
        <aside className="sidebar">
          <Logo />
          <nav className="nav" aria-label="Main">
            <NavLink to="/sessions" end className={({ isActive }) => (isActive ? "active" : "")}>
              Sessions
            </NavLink>
            {sessionLink("Review", `/sessions/${last}`, onReview)}
            {sessionLink("Compare", `/sessions/${last}/compare`, onCompare)}
            <NavLink to="/settings" className={({ isActive }) => (isActive ? "active" : "")}>
              Settings
            </NavLink>
          </nav>
          <div className="sidebar-foot">Session Compaction using Jev</div>
        </aside>
        <main className="main">{children}</main>
      </div>
    </LastSession.Provider>
  );
}

import { useState } from "react";
import * as Drawer from "@radix-ui/react-dialog";
import {
  BookOpen,
  LayoutDashboard,
  Files,
  History,
  KeyRound,
  Plus,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import {
  BrowserRouter,
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { useAuth } from "./auth";
import { Button } from "./components/ui/button";
import { AccountPage } from "./components/account";
import { ErrorBoundary } from "./components/error-boundary";
import { ErrorMessage } from "./components/common";
import { Login } from "./pages/login";
import { Workspace } from "./pages/workspace";
import { NewAnalysis } from "./pages/new-analysis";
import { Library } from "./pages/library";
import { Analysis } from "./pages/analysis";
import { Invites } from "./pages/invites";

function Shell() {
  const auth = useAuth();
  const location = useLocation();
  const [menu, setMenu] = useState(false);
  const [error, setError] = useState<unknown>();
  const [loggingOut, setLoggingOut] = useState(false);
  if (!auth.user)
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  const nav = [
    { to: "/", label: "工作台", Icon: LayoutDashboard },
    { to: "/library", label: "文献库", Icon: Files },
    { to: "/history", label: "分析记录", Icon: History },
    ...(auth.user.is_admin
      ? [{ to: "/invites", label: "邀请码", Icon: KeyRound }]
      : []),
  ];
  async function logout() {
    setLoggingOut(true);
    try {
      await auth.logout();
    } catch (error) {
      setError(error);
    } finally {
      setLoggingOut(false);
    }
  }
  const sidebar = (
    <>
      <Link to="/" className="brand" onClick={() => setMenu(false)}>
        <span className="brand-mark">
          <BookOpen size={23} aria-hidden="true" />
        </span>
        <span>
          文镜 AI<small>PaperLens</small>
        </span>
      </Link>
      <Button asChild className="mt-10 w-full">
        <Link to="/new" onClick={() => setMenu(false)}>
          <Plus size={18} aria-hidden="true" />
          新建分析
        </Link>
      </Button>
      <nav aria-label="主要导航" className="main-nav">
        {nav.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={() => setMenu(false)}
          >
            <Icon size={19} aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-note">
          <span className="text-primary">
            <BookOpen size={18} aria-hidden="true" />
          </span>
          <p>
            让每一个判断
            <br />
            都能回到原文。
          </p>
        </div>
        <div className="account">
          <Link
            to="/account"
            className={`account-main ${location.pathname === "/account" ? "is-active" : ""}`}
            onClick={() => setMenu(false)}
            aria-current={location.pathname === "/account" ? "page" : undefined}
          >
            <span className="avatar">{auth.user.email[0].toUpperCase()}</span>
            <span className="min-w-0 flex-1 text-left">
              <span className="block truncate text-xs font-medium">
                {auth.user.email}
              </span>
              <span className="mt-1 block text-xs text-secondary">
                {auth.user.is_admin ? "管理员" : "普通用户"} · 账号设置
              </span>
            </span>
          </Link>
          <Button
            variant="ghost"
            className="px-2"
            onClick={logout}
            disabled={loggingOut}
            aria-label="退出登录"
          >
            <LogOut size={17} aria-hidden="true" />
          </Button>
        </div>
        <ErrorMessage error={error} />
      </div>
    </>
  );
  return (
    <Drawer.Root open={menu} onOpenChange={setMenu}>
      <div className="app-layout">
        <a className="skip-link" href="#main-content">
          跳转到主要内容
        </a>
        <header className="mobile-header">
          <Link to="/" className="brand">
            <BookOpen size={23} aria-hidden="true" />
            <span>文镜 AI</span>
          </Link>
          <Drawer.Trigger asChild>
            <Button variant="ghost" aria-label="打开导航">
              <Menu size={22} aria-hidden="true" />
            </Button>
          </Drawer.Trigger>
        </header>
        <aside className="sidebar">{sidebar}</aside>
        <Drawer.Portal>
          <Drawer.Overlay className="sidebar-scrim" />
          <Drawer.Content className="mobile-sidebar">
            <Drawer.Title className="sr-only">主要导航</Drawer.Title>
            <Drawer.Description className="sr-only">
              打开工作台、文献库或分析记录。
            </Drawer.Description>
            <Drawer.Close asChild>
              <Button
                variant="ghost"
                className="absolute right-3 top-3 px-2"
                aria-label="关闭导航"
              >
                <X size={20} aria-hidden="true" />
              </Button>
            </Drawer.Close>
            {sidebar}
          </Drawer.Content>
        </Drawer.Portal>
        <div className="content-frame">
          <div className="topbar">
            <span>文献阅读与分析</span>
            <span className="flex items-center gap-2">
              <span className="size-1.5 rounded-full bg-primary" />
              个人工作空间
            </span>
          </div>
          <main
            id="main-content"
            className="main-content"
            key={location.pathname}
            tabIndex={-1}
          >
            {/* 页面级兜底：单个页面渲染失败时保留侧边栏，方便切走。 */}
            <ErrorBoundary compact>
              <Outlet />
            </ErrorBoundary>
          </main>
          <footer>
            文镜 AI · PaperLens <span>有据可查，保持思考。</span>
          </footer>
        </div>
      </div>
    </Drawer.Root>
  );
}

function AdminOnly() {
  const auth = useAuth();
  if (!auth.user?.is_admin) return <Navigate to="/" replace />;
  return <Invites />;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Shell />}>
          <Route index element={<Workspace />} />
          <Route path="new" element={<NewAnalysis />} />
          <Route path="library" element={<Library />} />
          <Route path="history" element={<Workspace history />} />
          <Route path="analyses/:id" element={<Analysis />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="invites" element={<AdminOnly />} />
          <Route
            path="*"
            element={
              <div className="empty-state">
                <h1>页面不存在</h1>
                <Button asChild>
                  <Link to="/">返回工作台</Link>
                </Button>
              </div>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

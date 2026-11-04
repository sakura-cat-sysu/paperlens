import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, queryKeys, type Schema } from "../api/client";
import { useAuth } from "../auth";
import { ErrorMessage } from "./common";

export function GuestNotice() {
  const { user } = useAuth();
  const guest = Boolean(user?.is_guest);
  const usage = useQuery({
    queryKey: queryKeys.usage,
    queryFn: () => api<Schema["UsageView"]>("/usage"),
    enabled: guest,
    refetchInterval: guest ? 10000 : false,
  });
  if (!guest) return null;
  return (
    <aside className="guest-notice" aria-label="游客空间与额度">
      <div className="guest-notice-heading">
        <strong>游客体验</strong>
        <span>
          今日剩余 {usage.data?.remaining ?? "—"} / {usage.data?.limit ?? "—"}{" "}
          次分析
        </span>
        <Link to="/login" className="text-link">
          登录正式账号
        </Link>
      </div>
      <p>
        此浏览器的独立空间，每天北京时间 08:00
        重置额度。清除浏览器数据后，可能无法找回文献和报告。
      </p>
      <ErrorMessage error={usage.error} />
    </aside>
  );
}

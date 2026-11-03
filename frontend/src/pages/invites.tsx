import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, Copy, KeyRound, Plus, ShieldCheck } from "lucide-react";
import { api, queryKeys, type Schema } from "../api/client";
import { Button } from "../components/ui/button";
import { Dialog } from "../components/ui/dialog";
import { Empty, ErrorMessage, Loading, formatDate } from "../components/common";

type Invite = Schema["InviteView"];
type Issued = Schema["InviteIssued"];

const stateLabels: Record<string, string> = {
  active: "可用",
  used: "已用完",
  expired: "已过期",
  revoked: "已吊销",
};

const roles = [
  {
    value: "member",
    title: "普通用户",
    description: "管理自己的文献与分析，看不到邀请码页面。",
  },
  {
    value: "admin",
    title: "管理员",
    description: "可以签发、查看和吊销邀请码，管理成员准入。",
  },
];

function group(code: string) {
  return code.replace(/(.{4})(?=.)/g, "$1-");
}

export function Invites() {
  const client = useQueryClient();
  const [issued, setIssued] = useState<Issued | null>(null);
  const [role, setRole] = useState("member");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<unknown>();

  const invites = useQuery({
    queryKey: queryKeys.invites,
    queryFn: () => api<Invite[]>("/admin/invites"),
  });

  const create = useMutation({
    mutationFn: (body: Schema["InviteCreate"]) =>
      api<Issued>("/admin/invites", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      setIssued(data);
      setCopied(false);
      setError(undefined);
      void client.invalidateQueries({ queryKey: queryKeys.invites });
    },
    onError: setError,
  });

  const revoke = useMutation({
    mutationFn: (id: string) =>
      api<Invite>(`/admin/invites/${id}/revoke`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.invites });
    },
    onError: setError,
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const days = Number(fields.get("expires_in_days"));
    create.mutate({
      note: String(fields.get("note") ?? ""),
      max_uses: Number(fields.get("max_uses")) || 1,
      expires_in_days: days > 0 ? days : null,
      grants_admin: role === "admin",
    });
  }

  async function copy(code: string) {
    try {
      await navigator.clipboard.writeText(group(code));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const active =
    invites.data?.filter((invite) => invite.state === "active").length ?? "—";

  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">WHO JOINS THE WORK</span>
          <h1>邀请码</h1>
          <p>签发邀请码，决定谁能加入，以及加入后拥有什么权限。</p>
        </div>
        <Button type="submit" form="invite-form" disabled={create.isPending}>
          <Plus size={18} aria-hidden="true" />
          {create.isPending ? "正在签发…" : "签发邀请码"}
        </Button>
      </div>

      <ErrorMessage error={error ?? invites.error} />

      <form id="invite-form" onSubmit={submit} className="analysis-form">
        <section>
          <div className="section-heading">
            <h2>
              <span className="step-number">01</span>设置权限
            </h2>
          </div>
          <p className="mb-5 text-sm leading-7 text-secondary">
            选择使用这个邀请码注册的成员，注册完成后获得的身份。
          </p>
          <div className="role-options">
            {roles.map((option) => (
              <label
                key={option.value}
                className={`role-option ${role === option.value ? "is-selected" : ""}`}
              >
                <input
                  type="radio"
                  name="role"
                  value={option.value}
                  checked={role === option.value}
                  onChange={() => setRole(option.value)}
                />
                <span className="role-option-text">
                  <strong>{option.title}</strong>
                  <span className="role-option-help">{option.description}</span>
                </span>
              </label>
            ))}
          </div>
        </section>

        <section className="question-panel">
          <h2>
            <span className="step-number">02</span>设置有效范围
          </h2>
          <div className="mt-6 space-y-5">
            <label className="field-label">
              备注
              <input
                name="note"
                type="text"
                maxLength={200}
                placeholder="例如：合作组成员"
              />
            </label>
            <label className="field-label">
              可用次数
              <input
                name="max_uses"
                type="number"
                min={1}
                max={100}
                defaultValue={1}
              />
            </label>
            <label className="field-label">
              有效天数
              <input
                name="expires_in_days"
                type="number"
                min={0}
                max={365}
                defaultValue={14}
              />
              <span className="field-help">填 0 表示永不过期</span>
            </label>
          </div>
          <div className="privacy-note">
            <ShieldCheck size={19} aria-hidden="true" />
            <p>
              邀请码在数据库中只保存摘要和掩码，明文仅在签发后显示一次。已签发的邀请码可以随时吊销。
            </p>
          </div>
        </section>
      </form>

      <section className="mt-10">
        <div className="section-heading">
          <h2>已签发</h2>
          <span className="text-sm text-secondary">
            {invites.data?.length ?? "—"} 个 <span className="mx-1">·</span>{" "}
            {active} 个可用
          </span>
        </div>
        {invites.isPending ? (
          <Loading />
        ) : invites.data?.length ? (
          <div className="invite-table">
            <table>
              <thead>
                <tr>
                  <th>邀请码</th>
                  <th>备注</th>
                  <th>权限</th>
                  <th>状态</th>
                  <th>用量</th>
                  <th>签发时间</th>
                  <th>到期时间</th>
                  <th className="invite-actions-head">操作</th>
                </tr>
              </thead>
              <tbody>
                {invites.data.map((invite) => (
                  <tr key={invite.id}>
                    <td className="invite-hint">{invite.code_hint}</td>
                    <td>{invite.note || "—"}</td>
                    <td>{invite.grants_admin ? "管理员" : "普通用户"}</td>
                    <td>
                      <span className={`status status-${invite.state}`}>
                        {stateLabels[invite.state] ?? invite.state}
                      </span>
                    </td>
                    <td>
                      {invite.used_count}/{invite.max_uses}
                    </td>
                    <td className="text-secondary">
                      {formatDate(invite.created_at)}
                    </td>
                    <td
                      className={
                        invite.state === "expired"
                          ? "text-danger"
                          : "text-secondary"
                      }
                    >
                      {invite.expires_at
                        ? formatDate(invite.expires_at)
                        : "永不过期"}
                    </td>
                    <td className="invite-actions">
                      <Button
                        variant="ghost"
                        onClick={() => revoke.mutate(invite.id)}
                        disabled={revoke.isPending || invite.state !== "active"}
                        aria-label={`吊销邀请码 ${invite.code_hint}`}
                      >
                        <Ban size={15} aria-hidden="true" />
                        吊销
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="还没有签发邀请码"
            description="设置权限和有效范围后，点击右上角签发邀请码。"
            action={false}
          />
        )}
      </section>

      <Dialog
        open={!!issued}
        onOpenChange={(open) => !open && setIssued(null)}
        title="邀请码已签发"
        description="明文只显示这一次，关闭后无法再次查看，请立即复制并转交给成员。"
      >
        {issued && (
          <div className="space-y-5">
            <div className="issued-code">
              <KeyRound size={19} aria-hidden="true" />
              <p className="issued-code-value">{group(issued.code)}</p>
            </div>
            <dl className="issued-meta">
              <div>
                <dt>注册后身份</dt>
                <dd>{issued.grants_admin ? "管理员" : "普通用户"}</dd>
              </div>
              <div>
                <dt>可用次数</dt>
                <dd>{issued.max_uses} 次</dd>
              </div>
              <div>
                <dt>有效期</dt>
                <dd>
                  {issued.expires_at
                    ? `${formatDate(issued.expires_at)} 前有效`
                    : "永不过期"}
                </dd>
              </div>
              {issued.note && (
                <div>
                  <dt>备注</dt>
                  <dd>{issued.note}</dd>
                </div>
              )}
            </dl>
            <div className="flex gap-3">
              <Button
                className="flex-1"
                onClick={() => void copy(issued.code)}
              >
                {copied ? (
                  <Check size={17} aria-hidden="true" />
                ) : (
                  <Copy size={17} aria-hidden="true" />
                )}
                {copied ? "已复制到剪贴板" : "复制邀请码"}
              </Button>
              <Button variant="outline" onClick={() => setIssued(null)}>
                完成
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}

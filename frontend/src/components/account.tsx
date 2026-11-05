import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { api, queryKeys, type Schema } from "../api/client";
import { useAuth } from "../auth";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { ErrorMessage, Loading, formatDate } from "./common";

type Account = Schema["AccountView"];
type ModelConfig = Schema["ModelConfigView"];
type Notice = { where: "personal" | "global" | "password"; text: string };
type DialogState = { scope: "personal" | "global"; config: ModelConfig | null };

const PROTOCOL_LABELS: Record<string, string> = {
  chat: "OpenAI 兼容",
  responses: "OpenAI Responses",
  messages: "Anthropic",
};
const step = (value: number) => String(value).padStart(2, "0");

function ConfigForm({
  idPrefix,
  config,
  pending,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  idPrefix: string;
  config: ModelConfig | null;
  pending: boolean;
  submitLabel: string;
  onSubmit: (body: Schema["ModelConfigUpdate"]) => void;
  onCancel: () => void;
}) {
  const [error, setError] = useState("");
  const saved = !!config?.configured;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const apiKey = String(fields.get("api_key") ?? "").trim();
    if (!saved && !apiKey) {
      setError("请填写 API Key。");
      return;
    }
    setError("");
    onSubmit({
      name: String(fields.get("name") ?? ""),
      api_key: apiKey,
      base_url: String(fields.get("base_url") ?? ""),
      model: String(fields.get("model") ?? ""),
      protocol: String(fields.get("protocol") ?? "chat"),
    });
  }

  return (
    <form onSubmit={submit} key={config?.id ?? "new"}>
      <div className="config-fields">
        <div>
          <label className="field-label" htmlFor={`${idPrefix}-name`}>
            配置备注
          </label>
          <input
            id={`${idPrefix}-name`}
            name="name"
            className="mt-2"
            type="text"
            maxLength={60}
            defaultValue={config?.name ?? ""}
            placeholder="例如：主账号 / 团队共用"
          />
        </div>
        <div>
          <label className="field-label" htmlFor={`${idPrefix}-model`}>
            模型名称
          </label>
          <input
            id={`${idPrefix}-model`}
            name="model"
            className="mt-2"
            type="text"
            maxLength={120}
            defaultValue={config?.model ?? ""}
            placeholder="例如 deepseek-flash"
          />
        </div>
        <div>
          <label className="field-label" htmlFor={`${idPrefix}-protocol`}>
            接口协议
          </label>
          <select
            id={`${idPrefix}-protocol`}
            name="protocol"
            className="mt-2"
            defaultValue={config?.protocol ?? "chat"}
          >
            <option value="chat">OpenAI 兼容（Chat Completions）</option>
            <option value="responses">OpenAI Responses</option>
            <option value="messages">Anthropic（Messages）</option>
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor={`${idPrefix}-api-key`}>
            API Key
          </label>
          <input
            id={`${idPrefix}-api-key`}
            name="api_key"
            className="mt-2"
            type="password"
            autoComplete="off"
            maxLength={400}
            aria-required={!saved}
            placeholder={
              saved
                ? `已保存 ${config?.api_key_hint}，留空表示不修改`
                : "必填，例如 sk-xxxxxxxxxxxx"
            }
            aria-describedby={`${idPrefix}-api-key-help`}
          />
          <p id={`${idPrefix}-api-key-help`} className="field-help mt-2">
            加密后保存在本机数据库，接口只回显掩码。
          </p>
        </div>
        <div>
          <label className="field-label" htmlFor={`${idPrefix}-base-url`}>
            API 根地址
          </label>
          <input
            id={`${idPrefix}-base-url`}
            name="base_url"
            className="mt-2"
            type="url"
            maxLength={300}
            defaultValue={config?.base_url ?? ""}
            placeholder="例如 https://api.deepseek.com"
          />
        </div>
      </div>
      <ErrorMessage error={error ? new Error(error) : undefined} />
      <div className="mt-6 flex flex-wrap gap-3">
        <Button type="submit" disabled={pending}>
          <KeyRound size={16} aria-hidden="true" />
          {pending ? "正在保存…" : submitLabel}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onCancel}
          disabled={pending}
        >
          取消
        </Button>
      </div>
    </form>
  );
}

function ConfigSection({
  stepNumber,
  title,
  badge,
  note,
  configs,
  notice,
  addLabel,
  emptyTitle,
  emptyHelp,
  onAdd,
  onEdit,
  onRemove,
  pending,
}: {
  stepNumber: number;
  title: string;
  badge?: ReactNode;
  note: string;
  configs: ModelConfig[];
  notice?: string;
  addLabel: string;
  emptyTitle: string;
  emptyHelp: string;
  onAdd: () => void;
  onEdit: (config: ModelConfig) => void;
  onRemove: (id: string) => void;
  pending: boolean;
}) {
  return (
    <section>
      <div className="section-heading">
        <h2>
          <span className="step-number">{step(stepNumber)}</span>
          {title}
          {badge}
        </h2>
        <Button variant="outline" onClick={onAdd}>
          <Plus size={16} aria-hidden="true" />
          {addLabel}
        </Button>
      </div>
      <p className="section-note">{note}</p>

      {configs.length ? (
        <ul className="config-list">
          {configs.map((item) => (
            <li key={item.id} className="config-row">
              <div className="min-w-0">
                <p className="config-name">{item.name}</p>
                <p className="config-meta">
                  {PROTOCOL_LABELS[item.protocol] ?? item.protocol} ·{" "}
                  {item.model || "未填模型"} ·{" "}
                  {item.configured
                    ? `密钥 ${item.api_key_hint}`
                    : "尚未填写密钥"}{" "}
                  · {item.base_url || "默认地址"}
                </p>
              </div>
              <div className="config-actions">
                <Button
                  variant="ghost"
                  onClick={() => onEdit(item)}
                  aria-label={`编辑 ${item.name}`}
                >
                  <Pencil size={15} aria-hidden="true" />
                  编辑
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => onRemove(item.id!)}
                  disabled={pending}
                  aria-label={`删除 ${item.name}`}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  删除
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="config-empty">
          <p className="config-empty-title">{emptyTitle}</p>
          <p className="config-empty-help">{emptyHelp}</p>
        </div>
      )}

      {notice && (
        <p role="status" className="section-notice">
          {notice}
        </p>
      )}
    </section>
  );
}

export function AccountPage() {
  const auth = useAuth();
  const client = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [dialogError, setDialogError] = useState<unknown>();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);

  const account = useQuery({
    queryKey: queryKeys.account,
    queryFn: () => api<Account>("/account"),
  });

  function refresh() {
    void client.invalidateQueries({ queryKey: queryKeys.account });
    void client.invalidateQueries({ queryKey: queryKeys.adminModels });
    void client.invalidateQueries({ queryKey: queryKeys.models });
    void client.invalidateQueries({ queryKey: ["capabilities"] });
  }
  function done(where: Notice["where"], text: string) {
    setNotice({ where, text });
    setError(undefined);
    setDialogError(undefined);
    setDialog(null);
    setPasswordOpen(false);
    refresh();
  }
  function openDialog(scope: DialogState["scope"], config: ModelConfig | null) {
    setDialog({ scope, config });
    setDialogError(undefined);
  }

  const password = useMutation({
    mutationFn: (body: Schema["PasswordChange"]) =>
      api<void>("/account/password", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => done("password", "密码已更新，其他设备上的登录已失效。"),
    onError: setDialogError,
  });

  const createConfig = useMutation({
    mutationFn: (body: Schema["ModelConfigUpdate"]) =>
      api<ModelConfig>("/account/models", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => done("personal", "个人配置已添加。"),
    onError: setDialogError,
  });

  const updateConfig = useMutation({
    mutationFn: (payload: { id: string; body: Schema["ModelConfigUpdate"] }) =>
      api<ModelConfig>(`/account/models/${payload.id}`, {
        method: "PUT",
        body: JSON.stringify(payload.body),
      }),
    onSuccess: () => done("personal", "个人配置已更新。"),
    onError: setDialogError,
  });

  const removeConfig = useMutation({
    mutationFn: (id: string) =>
      api<void>(`/account/models/${id}`, { method: "DELETE" }),
    onSuccess: () => done("personal", "个人配置已删除。"),
    onError: setError,
  });

  const createGlobal = useMutation({
    mutationFn: (body: Schema["ModelConfigUpdate"]) =>
      api<ModelConfig>("/admin/models", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => done("global", "全局配置已添加。"),
    onError: setDialogError,
  });

  const updateGlobal = useMutation({
    mutationFn: (payload: { id: string; body: Schema["ModelConfigUpdate"] }) =>
      api<ModelConfig>(`/admin/models/${payload.id}`, {
        method: "PUT",
        body: JSON.stringify(payload.body),
      }),
    onSuccess: () => done("global", "全局配置已更新。"),
    onError: setDialogError,
  });

  const removeGlobal = useMutation({
    mutationFn: (id: string) =>
      api<void>(`/admin/models/${id}`, { method: "DELETE" }),
    onSuccess: () => done("global", "全局配置已删除。"),
    onError: setError,
  });

  const data = account.data;

  function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const next = String(fields.get("new_password") ?? "");
    if (next !== String(fields.get("confirm_password") ?? "")) {
      setDialogError(new Error("两次输入的新密码不一致。"));
      return;
    }
    password.mutate(
      {
        current_password: String(fields.get("current_password") ?? ""),
        new_password: next,
      },
      { onSuccess: () => form.reset() },
    );
  }

  const isAdmin = !!auth.user?.is_admin;
  const configPending =
    createConfig.isPending ||
    updateConfig.isPending ||
    createGlobal.isPending ||
    updateGlobal.isPending;

  const dialogTitle = dialog
    ? dialog.config
      ? `编辑：${dialog.config.name}`
      : dialog.scope === "personal"
        ? "添加配置"
        : "添加全局配置"
    : "";
  const dialogDescription =
    dialog?.scope === "global"
      ? "全局配置对所有成员可见，成员在新建分析时可以选用。"
      : "个人配置只对你生效，新建分析时可以选用。";

  function submitConfig(body: Schema["ModelConfigUpdate"]) {
    if (!dialog) return;
    if (dialog.scope === "personal") {
      if (dialog.config) updateConfig.mutate({ id: dialog.config.id!, body });
      else createConfig.mutate(body);
    } else if (dialog.config) {
      updateGlobal.mutate({ id: dialog.config.id!, body });
    } else {
      createGlobal.mutate(body);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR ACCOUNT</span>
          <h1>账号设置</h1>
          <p>查看账号状态、修改密码，并维护分析可用的模型配置。</p>
        </div>
      </div>

      <ErrorMessage error={account.error} />
      <ErrorMessage error={error} />

      {account.isPending ? (
        <Loading />
      ) : data ? (
        <div className="account-page">
          <section>
            <div className="section-heading">
              <h2>
                <span className="step-number">{step(1)}</span>账号状态
              </h2>
            </div>
            <dl className="issued-meta">
              <div>
                <dt>邮箱</dt>
                <dd className="break-all">{data.user.email}</dd>
              </div>
              <div>
                <dt>身份</dt>
                <dd>{data.user.is_admin ? "管理员" : "普通用户"}</dd>
              </div>
              <div>
                <dt>注册时间</dt>
                <dd>{formatDate(data.created_at)}</dd>
              </div>
              <div>
                <dt>今日分析</dt>
                <dd>
                  {data.usage.used} / {data.usage.limit} 次，剩余{" "}
                  {data.usage.remaining} 次
                </dd>
              </div>
            </dl>
          </section>

          <ConfigSection
            stepNumber={2}
            title="我的模型配置"
            note="可以保存多套配置（不同账号、不同服务商）。新建分析时自己选用哪一套。"
            configs={data.models}
            notice={notice?.where === "personal" ? notice.text : undefined}
            addLabel="添加配置"
            emptyTitle="还没有可用的模型配置"
            emptyHelp={
              isAdmin
                ? "你是管理员：可以在下方配置全局模型供所有人使用，也可以先给自己加一套。"
                : "可以等管理员配置好全局模型，也可以现在自己加一套——个人配置只对你生效。"
            }
            onAdd={() => openDialog("personal", null)}
            onEdit={(config) => openDialog("personal", config)}
            onRemove={removeConfig.mutate}
            pending={removeConfig.isPending}
          />

          {isAdmin && (
            <ConfigSection
              stepNumber={3}
              title="全局模型配置"
              badge={
                <span className="admin-badge">
                  <ShieldCheck size={13} aria-hidden="true" />
                  管理员
                </span>
              }
              note="所有成员都能选用这些配置。可以配置多套（不同服务商或不同额度），成员在分析时自己挑。"
              configs={data.global_models}
              notice={notice?.where === "global" ? notice.text : undefined}
              addLabel="添加全局配置"
              emptyTitle="还没有全局配置"
              emptyHelp="添加后所有成员都能在新建分析时选用；每位成员也可以另外配置自己的。"
              onAdd={() => openDialog("global", null)}
              onEdit={(config) => openDialog("global", config)}
              onRemove={removeGlobal.mutate}
              pending={removeGlobal.isPending}
            />
          )}

          <section>
            <div className="section-heading">
              <h2>
                <span className="step-number">{step(isAdmin ? 4 : 3)}</span>
                修改密码
              </h2>
              <Button variant="outline" onClick={() => setPasswordOpen(true)}>
                修改密码
              </Button>
            </div>
            <p className="section-note">
              修改后其他设备上的登录会立即失效，当前设备保持登录。
            </p>
            {notice?.where === "password" && (
              <p role="status" className="section-notice">
                {notice.text}
              </p>
            )}
          </section>
        </div>
      ) : null}

      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open) setDialog(null);
        }}
        title={dialogTitle}
        description={dialogDescription}
      >
        {dialog && (
          <>
            <ErrorMessage error={dialogError} />
            <ConfigForm
              idPrefix={
                dialog.config
                  ? `edit-${dialog.config.id}`
                  : `${dialog.scope}-new`
              }
              config={dialog.config}
              pending={configPending}
              submitLabel={dialog.config ? "保存修改" : "保存"}
              onSubmit={submitConfig}
              onCancel={() => setDialog(null)}
            />
          </>
        )}
      </Dialog>

      <Dialog
        open={passwordOpen}
        onOpenChange={(open) => {
          if (!open) setPasswordOpen(false);
        }}
        title="修改密码"
        description="修改后其他设备上的登录会立即失效，当前设备保持登录。"
      >
        <form onSubmit={submitPassword}>
          <div className="account-fields">
            <div>
              <label className="field-label" htmlFor="current-password">
                当前密码
              </label>
              <input
                id="current-password"
                name="current_password"
                className="mt-2"
                type="password"
                autoComplete="current-password"
                required
                maxLength={128}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="new-password">
                新密码
              </label>
              <input
                id="new-password"
                name="new_password"
                className="mt-2"
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                maxLength={128}
                aria-describedby="new-password-help"
              />
              <p id="new-password-help" className="field-help mt-2">
                至少 12 个字符
              </p>
            </div>
            <div>
              <label className="field-label" htmlFor="confirm-password">
                确认新密码
              </label>
              <input
                id="confirm-password"
                name="confirm_password"
                className="mt-2"
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                maxLength={128}
              />
            </div>
          </div>
          <ErrorMessage error={dialogError} />
          <div className="mt-6 flex flex-wrap gap-3">
            <Button type="submit" disabled={password.isPending}>
              {password.isPending ? "正在更新…" : "更新密码"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPasswordOpen(false)}
              disabled={password.isPending}
            >
              取消
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

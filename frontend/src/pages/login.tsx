import { useState, type FormEvent } from "react";
import { BookOpen, ArrowRight, Quote } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import { api, type Schema } from "../api/client";
import { useAuth } from "../auth";
import { Button } from "../components/ui/button";
import { ErrorMessage } from "../components/common";

export function Login() {
  const auth = useAuth();
  const [register, setRegister] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const config = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Schema["Capabilities"]>("/capabilities"),
  });
  if (auth.user) return <Navigate to="/" replace />;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setPending(true);
    setError(undefined);
    try {
      const result = await api<Schema["AuthView"]>(
        register ? "/auth/register" : "/auth/login",
        {
          method: "POST",
          body: JSON.stringify({
            email: fields.get("email"),
            password: fields.get("password"),
          }),
        },
      );
      auth.accept(result);
    } catch (error) {
      setError(error);
    } finally {
      setPending(false);
    }
  }
  return (
    <main className="login-layout">
      <section className="login-story">
        <a href="/" className="brand">
          <span className="brand-mark">
            <BookOpen size={24} aria-hidden="true" />
          </span>
          <span>
            文镜 AI<small>PaperLens</small>
          </span>
        </a>
        <div className="login-statement">
          <span className="eyebrow">READ ACROSS. THINK DEEPER.</span>
          <h1>
            让文献之间的
            <br />
            联系，清晰可见。
          </h1>
          <p>
            从一个研究问题出发，读懂不同文献的观点，
            <br className="hidden lg:block" />
            让每个判断都能回到原文。
          </p>
          <div className="story-example">
            <Quote size={24} aria-hidden="true" />
            <p>共同观点、机制差异，还是结论冲突？</p>
            <span>把比较建立在可追溯的证据上。</span>
            <div className="story-lines">
              <i />
              <i />
              <i />
            </div>
          </div>
        </div>
        <p className="text-sm text-secondary">跨语言文献阅读与分析工作台</p>
      </section>
      <section className="login-form-region">
        <form onSubmit={submit} className="login-form">
          <span className="eyebrow">你的研究，从这里继续</span>
          <h2>{register ? "创建账号" : "登录文镜"}</h2>
          <p className="text-secondary">保存文献、分析进度与有据可查的报告。</p>
          <div className="mt-8 space-y-5">
            <label className="field-label">
              邮箱
              <input
                name="email"
                type="email"
                autoComplete="email"
                required
                maxLength={254}
                placeholder="you@example.com"
              />
            </label>
            <div>
              <label className="field-label" htmlFor="password">
                密码
              </label>
              <input
                id="password"
                name="password"
                className="mt-2"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                required
                minLength={12}
                maxLength={128}
                aria-describedby="password-help"
              />
              <p id="password-help" className="field-help mt-2">
                至少 12 个字符
              </p>
            </div>
          </div>
          <ErrorMessage error={error ?? config.error} />
          <Button className="mt-6 w-full" disabled={pending}>
            {pending ? "正在处理…" : register ? "创建账号并登录" : "登录"}
            <ArrowRight size={17} aria-hidden="true" />
          </Button>
          {config.data?.allow_registration ? (
            <button
              type="button"
              className="mt-5 w-full text-sm text-primary underline-offset-4 hover:underline"
              onClick={() => {
                setRegister(!register);
                setError(undefined);
              }}
            >
              {register ? "已有账号？前往登录" : "还没有账号？创建账号"}
            </button>
          ) : (
            <p className="mt-5 text-sm text-secondary">
              账号由管理员开通。如需使用或重置密码，请联系管理员。
            </p>
          )}
        </form>
      </section>
    </main>
  );
}

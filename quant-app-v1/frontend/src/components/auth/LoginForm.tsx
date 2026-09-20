import { useState } from "react";
import { useAuth } from "@/context/AuthContext";

export default function LoginForm() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try { await login(email, password); }
    catch (err: any) { setError(err.message); }
    finally { setSubmitting(false); }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 320 }}>
      <input
        type="email" placeholder="Email" value={email} autoComplete="email"
        onChange={(e) => setEmail(e.target.value)} required
        style={{ padding: 8, border: "1px solid rgba(255,255,255,0.12)", borderRadius: 4, background: "#0d1117", color: "#e6edf3" }}
      />
      <input
        type="password" placeholder="Password" value={password} autoComplete="current-password"
        onChange={(e) => setPassword(e.target.value)} required
        style={{ padding: 8, border: "1px solid rgba(255,255,255,0.12)", borderRadius: 4, background: "#0d1117", color: "#e6edf3" }}
      />
      {error && <div style={{ color: "#f8517a", fontSize: 12 }}>{error}</div>}
      <button type="submit" disabled={submitting || !email || !password} style={{ padding: 8, border: "1px solid rgba(255,255,255,0.2)", borderRadius: 4, background: "#633cff", color: "#fff" }}>
        {submitting ? "Signing in…" : "Sign In"}
      </button>
    </form>
  );
}

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api";
import styles from "./Login.module.css";

export default function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(password);
      const userId = localStorage.getItem("userId");
      navigate(userId ? "/digest" : "/onboarding");
    } catch (err) {
      setError("Wrong password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.logo}>
          ourak<span>.</span>
        </div>
        <p className={styles.subtitle}>Research paper discovery for your lab</p>
        <form className={styles.form} onSubmit={handleSubmit}>
          <input
            className={styles.input}
            type="password"
            placeholder="Lab password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />
          <button className={styles.button} type="submit" disabled={loading || !password}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
          {error && <p className={styles.error}>{error}</p>}
        </form>
      </div>
    </div>
  );
}

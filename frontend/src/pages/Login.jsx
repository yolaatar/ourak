import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, getProfiles } from "../api";
import { useUser } from "../UserContext";
import styles from "./Login.module.css";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setUser } = useUser();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await login(username, password);
      setUser({ id: data.user_id, name: data.username });

      // Check if user has profiles — if so, go to digest
      const profiles = await getProfiles();
      if (profiles.length > 0) {
        navigate(`/digest?profile=${profiles[0].id}`);
      } else {
        navigate("/onboarding");
      }
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
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
          <input
            className={styles.input}
            type="password"
            placeholder="Lab password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className={styles.button} type="submit" disabled={loading || !username || !password}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
          {error && <p className={styles.error}>{error}</p>}
        </form>
      </div>
    </div>
  );
}

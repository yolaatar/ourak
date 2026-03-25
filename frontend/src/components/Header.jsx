import { useNavigate } from "react-router-dom";
import { logout } from "../api";
import styles from "./Header.module.css";

export default function Header({ userName }) {
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    localStorage.clear();
    navigate("/login");
  }

  return (
    <header className={styles.header}>
      <div className={styles.logo}>
        ourak<span>.</span>
      </div>
      <div className={styles.right}>
        {userName && <span className={styles.userName}>{userName}</span>}
        <button className={styles.logoutBtn} onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </header>
  );
}

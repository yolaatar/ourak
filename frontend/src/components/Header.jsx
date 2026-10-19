import { useNavigate } from "react-router-dom";
import { logout } from "../api";
import { useUser } from "../UserContext";
import styles from "./Header.module.css";

export default function Header() {
  const navigate = useNavigate();
  const { user } = useUser();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <header className={styles.header}>
      <div className={styles.logo}>
        ourak<span>.</span>
      </div>
      <div className={styles.right}>
        {user?.name && <span className={styles.userName}>{user.name}</span>}
        <button className={styles.logoutBtn} onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </header>
  );
}

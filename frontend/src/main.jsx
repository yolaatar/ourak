import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { UserProvider } from "./UserContext";
import ThemeToggle from "./components/ThemeToggle";
import "./styles/globals.css";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Digest from "./pages/Digest";

// Apply saved theme on initial load
const savedTheme = localStorage.getItem("theme") || "dark";
document.documentElement.dataset.theme = savedTheme;

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <UserProvider>
      <ThemeToggle />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/digest" element={<Digest />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </UserProvider>
  </StrictMode>
);

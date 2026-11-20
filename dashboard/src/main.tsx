import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "./styles.css";
import Layout from "./components/Layout";
import SessionsPage from "./pages/SessionsPage";
import ReviewPage from "./pages/ReviewPage";
import ComparePage from "./pages/ComparePage";
import SettingsPage from "./pages/SettingsPage";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/sessions" replace />} />
          <Route path="/sessions" element={<SessionsPage />} />
          <Route path="/sessions/:id" element={<ReviewPage />} />
          <Route path="/sessions/:id/compare" element={<ComparePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/sessions" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  </React.StrictMode>,
);

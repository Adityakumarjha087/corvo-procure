import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { Layout } from "./components/Layout";
import "./index.css";
import ChatPage from "./pages/Chat";
import ContractsPage from "./pages/Contracts";
import DataPage from "./pages/DataAudit";
import Overview from "./pages/Overview";
import PolicyPage from "./pages/Policy";
import SuppliersPage from "./pages/Suppliers";
import Workspace from "./pages/Workspace";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/workspace/:runId" element={<Workspace />} />
          <Route path="/policy" element={<PolicyPage />} />
          <Route path="/contracts" element={<ContractsPage />} />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/data" element={<DataPage />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      </Layout>
      <Toaster position="bottom-right" theme="system" richColors closeButton toastOptions={{ style: { fontFamily: "Inter, system-ui, sans-serif" } }} />
    </BrowserRouter>
  </React.StrictMode>,
);

import { Routes, Route, Link, useLocation } from "react-router-dom";
import MerchantOnboarding from "./pages/MerchantOnboarding";
import DemandDashboard from "./pages/DemandDashboard";
import MerchantCompetition from "./pages/MerchantCompetition";
import OfferMarketplace from "./pages/OfferMarketplace";
import AllocationView from "./pages/AllocationView";
import PaymentSuccess from "./pages/PaymentSuccess";
import "./App.css";

const NAV_ITEMS = [
  { path: "/", label: "Demand", icon: "📊" },
  { path: "/merchant", label: "Merchant", icon: "🏪" },
];

export default function App() {
  const location = useLocation();

  return (
    <div className="app">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="logo" style={{ textDecoration: "none" }}>
            <span className="logo-icon">⚡</span>
            <span className="logo-text">ReClaim</span>
          </Link>
          <nav style={{ display: "flex", gap: 8 }}>
            {NAV_ITEMS.map((n) => (
              <Link
                key={n.path}
                to={n.path}
                className={`nav-pill ${
                  location.pathname === n.path ||
                  (n.path !== "/" && location.pathname.startsWith(n.path))
                    ? "nav-active"
                    : ""
                }`}
              >
                {n.icon} {n.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      {/* ── Main content ───────────────────────────────────── */}
      <main className="main">
        <Routes>
          {/* Customer-facing */}
          <Route path="/" element={<DemandDashboard />} />
          <Route path="/pools/:poolId/competition" element={<MerchantCompetition />} />
          <Route path="/pools/:poolId/marketplace" element={<OfferMarketplace />} />
          <Route path="/pools/:poolId/allocations" element={<AllocationView />} />
          <Route path="/payment-success" element={<PaymentSuccess />} />

          {/* Merchant-facing */}
          <Route path="/merchant" element={<MerchantOnboarding />} />
        </Routes>
      </main>
    </div>
  );
}

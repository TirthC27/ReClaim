import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchOffers, selectOffer } from "../api";
import { useDemoSession } from "../contexts/DemoSessionContext";

const CATEGORY_MAP = {
  discount: { label: "Best Price", icon: "💰", color: "#10b981" },
  gift: { label: "Best Value", icon: "🎁", color: "#6366f1" },
  bundle: { label: "Bundle", icon: "📦", color: "#f59e0b" },
  warranty: { label: "Protection", icon: "🛡️", color: "#3b82f6" },
  upgrade: { label: "Best Value", icon: "⬆️", color: "#6366f1" },
  service: { label: "Best Value", icon: "🔧", color: "#6366f1" },
  hybrid: { label: "Best Value", icon: "✨", color: "#8b5cf6" },
};

export default function OfferMarketplace() {
  const { poolId } = useParams();
  const navigate = useNavigate();
  const { demandSignalId, setDemandSignalId } = useDemoSession();
  const [offers, setOffers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(null);
  const [error, setError] = useState("");
  const [localSignalId, setLocalSignalId] = useState(demandSignalId || "");

  useEffect(() => {
    fetchOffers(poolId, "validated")
      .then(setOffers)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [poolId]);

  const handleSelect = async (offerId) => {
    const sid = localSignalId || demandSignalId;
    if (!sid) {
      setError("Enter a demand_signal_id first (simulate being a specific customer).");
      return;
    }
    setDemandSignalId(sid);
    setSelecting(offerId);
    setError("");
    try {
      const result = await selectOffer(offerId, sid);
      // Redirect to payment
      if (result.payment_link_url) {
        window.location.href = result.payment_link_url;
      } else {
        navigate(`/payment-success?order_id=${result.order_id}`);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setSelecting(null);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="step-badge">🛒</div>
        <div>
          <h2>Offer Marketplace</h2>
          <p className="subtitle">
            Choose the best offer for pool{" "}
            <code>{String(poolId).slice(0, 8)}…</code>
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Signal ID input for demo */}
      <div className="form-group" style={{ marginBottom: 24 }}>
        <label htmlFor="signal-id">Your Demand Signal ID (demo)</label>
        <input
          id="signal-id"
          type="text"
          placeholder="Paste your demand_signal_id..."
          value={localSignalId}
          onChange={(e) => setLocalSignalId(e.target.value)}
        />
        <span className="hint">
          This identifies which customer you are — required for allocation-fair offer selection.
        </span>
      </div>

      {loading ? (
        <div className="skeleton-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 140 }} />
          ))}
        </div>
      ) : offers.length === 0 ? (
        <div className="empty-state">
          <p>No validated offers available for this pool yet.</p>
        </div>
      ) : (
        <div className="product-list">
          {offers.map((o) => {
            const cat = CATEGORY_MAP[o.offer_type] || CATEGORY_MAP.hybrid;
            return (
              <div
                key={o.id}
                className="product-row"
                style={{
                  flexDirection: "column",
                  alignItems: "stretch",
                  gap: 12,
                  borderLeft: `4px solid ${cat.color}`,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <span style={{ fontSize: "1.5rem", marginRight: 8 }}>{cat.icon}</span>
                    <span className="badge" style={{ background: cat.color + "22", color: cat.color, marginRight: 8 }}>
                      {cat.label}
                    </span>
                    <strong style={{ fontSize: "1.2rem" }}>
                      ₹{Number(o.price).toLocaleString("en-IN")}
                    </strong>
                  </div>
                </div>

                {o.description && (
                  <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem", margin: 0, lineHeight: 1.5 }}>
                    {o.description}
                  </p>
                )}

                {o.bundled_items && o.bundled_items.length > 0 && (
                  <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                    🎁 Includes: {o.bundled_items.join(", ")}
                  </div>
                )}

                <button
                  className="btn btn-primary"
                  disabled={selecting === o.id || !localSignalId}
                  onClick={() => handleSelect(o.id)}
                  style={{ alignSelf: "flex-start" }}
                >
                  {selecting === o.id ? (
                    <><span className="spinner" /> Processing…</>
                  ) : (
                    "Select & Pay →"
                  )}
                </button>
              </div>
            );
          })}
        </div>
      )}

      <button
        className="btn"
        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)", border: "1px solid var(--border)", marginTop: 16 }}
        onClick={() => navigate(`/pools/${poolId}/competition`)}
      >
        ← Back to Competition
      </button>
    </div>
  );
}

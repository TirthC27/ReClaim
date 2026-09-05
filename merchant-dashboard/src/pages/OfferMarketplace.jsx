import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchBundleOffers, selectBundleOffer } from "../api";

const STATUS_CONFIG = {
  FULLY_FULFILLED: { label: "Full Coverage", icon: "✅", color: "#10b981" },
  PARTIALLY_FULFILLED: { label: "Partial Coverage", icon: "⚠️", color: "#f59e0b" },
  UNFULFILLED: { label: "Unavailable", icon: "❌", color: "#ef4444" },
};

function PartialFulfillmentBanner({ offer }) {
  const snapshot = offer.allocation_snapshot || {};
  const unfulfilled = snapshot.unfulfilled_items || [];
  const pct = offer.coverage_percentage ?? 0;

  return (
    <div
      style={{
        background: "#fef3c7",
        border: "1px solid #fbbf24",
        borderRadius: 8,
        padding: "12px 16px",
        marginBottom: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: "1.2rem" }}>⚠️</span>
        <strong style={{ color: "#92400e" }}>
          Partial Fulfillment — {pct.toFixed(1)}% of your basket covered
        </strong>
      </div>
      <p style={{ fontSize: "0.88rem", color: "#78350f", margin: "0 0 8px" }}>
        Some items in your cart are currently unavailable. The following items will{" "}
        <strong>not</strong> be included in this order:
      </p>
      <ul style={{ margin: 0, paddingLeft: 20, fontSize: "0.88rem", color: "#92400e" }}>
        {unfulfilled.map((item, i) => (
          <li key={i}>
            <strong>{item.sku}</strong> × {item.quantity}{" "}
            <span style={{ opacity: 0.7 }}>({item.reason})</span>
          </li>
        ))}
      </ul>
      <p style={{ fontSize: "0.83rem", color: "#78350f", margin: "8px 0 0" }}>
        By continuing, you acknowledge that you are purchasing only the available items listed above.
      </p>
    </div>
  );
}

export default function OfferMarketplace() {
  const { poolId } = useParams();
  const navigate = useNavigate();
  const [offers, setOffers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchBundleOffers(poolId, "validated")
      .then(setOffers)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [poolId]);

  const handleSelect = async (offerId) => {
    setSelecting(offerId);
    setError("");
    try {
      const result = await selectBundleOffer(offerId);
      if (result.payment_link_url) {
        window.location.href = result.payment_link_url;
      } else {
        navigate(`/payment-success?bundle_offer_id=${offerId}`);
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
          <h2>Bundle Offer Marketplace</h2>
          <p className="subtitle">
            Choose the best offer for pool{" "}
            <code>{String(poolId).slice(0, 8)}…</code>
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="skeleton-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 180 }} />
          ))}
        </div>
      ) : offers.length === 0 ? (
        <div className="empty-state">
          <p>No validated bundle offers available for this pool yet.</p>
        </div>
      ) : (
        <div className="product-list">
          {offers.map((o) => {
            const isPartial = o.fulfillment_status === "PARTIALLY_FULFILLED";
            const isUnfulfilled = o.fulfillment_status === "UNFULFILLED";
            const statusCfg = STATUS_CONFIG[o.fulfillment_status] || STATUS_CONFIG.FULLY_FULFILLED;
            const borderColor = statusCfg.color;

            return (
              <div
                key={o.id}
                className="product-row"
                style={{
                  flexDirection: "column",
                  alignItems: "stretch",
                  gap: 12,
                  borderLeft: `4px solid ${borderColor}`,
                  opacity: isUnfulfilled ? 0.6 : 1,
                }}
              >
                {/* Header row */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <span style={{ fontSize: "1.4rem", marginRight: 8 }}>{statusCfg.icon}</span>
                    <span
                      className="badge"
                      style={{ background: borderColor + "22", color: borderColor, marginRight: 8 }}
                    >
                      {statusCfg.label}
                    </span>
                    {o.merchant_count > 1 && (
                      <span
                        className="badge"
                        style={{ background: "#6366f122", color: "#6366f1", marginRight: 8 }}
                      >
                        {o.merchant_count} Merchants
                      </span>
                    )}
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <strong style={{ fontSize: "1.3rem" }}>
                      ₹{Number(o.total_price).toLocaleString("en-IN")}
                    </strong>
                    {o.bundle_discount > 0 && (
                      <div style={{ fontSize: "0.82rem", color: "#10b981" }}>
                        Save ₹{Number(o.bundle_discount).toLocaleString("en-IN")}
                      </div>
                    )}
                  </div>
                </div>

                {/* Coverage progress bar */}
                {o.coverage_percentage != null && (
                  <div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: "0.82rem",
                        color: "var(--text-secondary)",
                        marginBottom: 4,
                      }}
                    >
                      <span>Coverage</span>
                      <span>
                        {o.fulfilled_units}/{o.requested_units} units ({Number(o.coverage_percentage).toFixed(1)}%)
                      </span>
                    </div>
                    <div
                      style={{
                        height: 6,
                        background: "var(--bg-secondary)",
                        borderRadius: 3,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${o.coverage_percentage}%`,
                          background: borderColor,
                          borderRadius: 3,
                          transition: "width 0.4s ease",
                        }}
                      />
                    </div>
                  </div>
                )}

                {/* Line items breakdown */}
                {o.line_items && o.line_items.length > 0 && (
                  <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                    {o.line_items.map((li, i) => (
                      <div
                        key={i}
                        style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}
                      >
                        <span>📦 {li.product_group_id?.slice(0, 8)}… ×{li.quantity}</span>
                        <span>₹{Number(li.line_total).toLocaleString("en-IN")}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Partial fulfillment banner */}
                {isPartial && <PartialFulfillmentBanner offer={o} />}

                {/* CTA button */}
                <button
                  className={isPartial ? "btn" : "btn btn-primary"}
                  disabled={selecting === o.id || isUnfulfilled}
                  onClick={() => handleSelect(o.id)}
                  style={{
                    alignSelf: "flex-start",
                    background: isPartial ? "#f59e0b" : undefined,
                    color: isPartial ? "#fff" : undefined,
                  }}
                >
                  {selecting === o.id ? (
                    <><span className="spinner" /> Processing…</>
                  ) : isPartial ? (
                    "Continue with Available Items →"
                  ) : isUnfulfilled ? (
                    "Unavailable"
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
        style={{
          background: "var(--bg-secondary)",
          color: "var(--text-secondary)",
          border: "1px solid var(--border)",
          marginTop: 16,
        }}
        onClick={() => navigate(`/pools/${poolId}/competition`)}
      >
        ← Back to Competition
      </button>
    </div>
  );
}

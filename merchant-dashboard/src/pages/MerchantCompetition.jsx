import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchOffers, generateOffers } from "../api";
import { supabase } from "../supabaseClient";
import { useDemoSession } from "../contexts/DemoSessionContext";

export default function MerchantCompetition() {
  const { poolId } = useParams();
  const navigate = useNavigate();
  const { setPoolId } = useDemoSession();
  const [offers, setOffers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [buyerAgentResult, setBuyerAgentResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setPoolId(poolId);
  }, [poolId]);

  const load = async () => {
    try {
      const data = await fetchOffers(poolId);
      setOffers(data);
      setLoading(false);
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [poolId]);

  useEffect(() => {
    if (!supabase) return;
    const channel = supabase
      .channel("offers_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "offers" },
        () => load()
      )
      .subscribe();
    return () => supabase.removeChannel(channel);
  }, [poolId]);

  const handleGenerate = async () => {
    setGenerating(true);
    setBuyerAgentResult(null);
    setError("");
    try {
      const res = await generateOffers(poolId);
      if (res.failures > 0) {
        setError(
          `Offer generation completed with ${res.failures} failures. Details: ${JSON.stringify(
            res.failure_details
          )}`
        );
      }
      if (res.buyer_agent) {
        setBuyerAgentResult(res.buyer_agent);
      }
      await load();
    } catch (e) {
      setError(e.message || "Failed to trigger offer generation");
    } finally {
      setGenerating(false);
    }
  };

  const statusColor = (s) => {
    switch (s) {
      case "validated": case "selected": return "var(--success)";
      case "rejected": return "var(--error)";
      case "candidate": return "var(--warning)";
      default: return "var(--text-muted)";
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="step-badge">🤖</div>
        <div>
          <h2>Merchant Competition</h2>
          <p className="subtitle">
            Watch agents compete for pool{" "}
            <code>{String(poolId).slice(0, 8)}…</code>
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {generating ? (
        <div className="skeleton-list" style={{ textAlign: "center", padding: "40px" }}>
           <h3>🤖 Your Agent Evaluating a best offer...</h3>
           <p className="subtitle">Analyzing value, price, and bundles across competing merchants.</p>
           <div className="spinner" style={{ margin: "20px auto", width: 40, height: 40 }}></div>
        </div>
      ) : loading ? (
        <div className="skeleton-list">
          {[1, 2].map((i) => (
            <div key={i} className="skeleton" style={{ height: 120 }} />
          ))}
        </div>
      ) : offers.length === 0 ? (
        <div className="empty-state">
          <p>No offers yet. Trigger offer generation for this pool.</p>
          <button
            className="btn btn-primary"
            onClick={handleGenerate}
            disabled={generating}
            style={{ marginTop: 12 }}
          >
            ⚡ Generate Offers
          </button>
        </div>
      ) : (
        <div className="product-list">
          {buyerAgentResult && buyerAgentResult.ranking && buyerAgentResult.ranking.length > 0 && (
            <div className="alert alert-info" style={{ marginBottom: "20px" }}>
              <h4>Buyer Agent Evaluation Complete</h4>
              <ul style={{ margin: "10px 0 0 20px" }}>
                {buyerAgentResult.ranking.map((r, i) => (
                  <li key={i}><strong>Rank {r.rank}:</strong> {r.reasoning}</li>
                ))}
              </ul>
            </div>
          )}
          {offers.map((o) => (
            <div key={o.id} className="product-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <strong style={{ fontSize: "1.1rem" }}>
                    {o.buyer_rank ? `#${o.buyer_rank} ` : ''}{o.offer_type?.toUpperCase()} — ₹{Number(o.price).toLocaleString("en-IN")}
                  </strong>
                  <span className="product-meta" style={{ display: "block" }}>
                    Merchant: {String(o.merchant_id).slice(0, 8)}…
                  </span>
                </div>
                <span className="badge" style={{ background: statusColor(o.status) + "22", color: statusColor(o.status) }}>
                  {o.status}
                </span>
              </div>

              {o.description && (
                <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem", margin: 0 }}>
                  {o.description}
                </p>
              )}

              {o.strategy_reasoning && (
                <details style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                  <summary style={{ cursor: "pointer" }}>Strategy reasoning</summary>
                  <pre style={{ whiteSpace: "pre-wrap", marginTop: 8, background: "var(--bg-input)", padding: 12, borderRadius: 8 }}>
                    {JSON.stringify(o.strategy_reasoning, null, 2)}
                  </pre>
                </details>
              )}

              {o.bundled_items && o.bundled_items.length > 0 && (
                <div style={{ fontSize: "0.85rem" }}>
                  🎁 Bundled: {o.bundled_items.join(", ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
        <button className="btn btn-primary" onClick={() => navigate(`/pools/${poolId}/marketplace`)}>
          View Marketplace →
        </button>
        <button
          className="btn"
          style={{ background: "var(--bg-secondary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
          onClick={handleGenerate}
          disabled={generating}
        >
          ⚡ Re-generate Offers
        </button>
        <button className="btn" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)", border: "1px solid var(--border)" }} onClick={() => navigate("/")}>
          ← Back
        </button>
      </div>
    </div>
  );
}

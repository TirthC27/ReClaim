import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchOffers, generateOffers, fetchPoolSignals, fetchNegotiationRounds, negotiatePool } from "../api";
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
  const [signals, setSignals] = useState([]);
  const [error, setError] = useState("");
  const [negotiationRounds, setNegotiationRounds] = useState([]);

  useEffect(() => {
    setPoolId(poolId);
  }, [poolId]);

  const load = async () => {
    try {
      const data = await fetchOffers(poolId, null, "expired");
      setOffers(data);
      const signalsData = await fetchPoolSignals(poolId);
      setSignals(signalsData.signals || []);
      
      const roundsData = await fetchNegotiationRounds(poolId);
      setNegotiationRounds(roundsData.rounds || []);
      
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
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "offer_negotiation_rounds" },
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

  const handleNegotiate = async () => {
    setGenerating(true);
    setBuyerAgentResult(null);
    setError("");
    try {
      const res = await negotiatePool(poolId);
      if (res.error) {
        setError(res.error);
      }
      if (res.buyer_agent) {
        setBuyerAgentResult(res.buyer_agent);
      }
      await load();
    } catch (e) {
      setError(e.message || "Failed to trigger negotiation");
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

      <div style={{ padding: "16px", background: "var(--bg-secondary)", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h3 style={{ margin: 0 }}>Action Control</h3>
          <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Trigger AI negotiation for this pool to allocate offers.
          </p>
        </div>
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            className="btn btn-primary"
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? "Generating..." : "⚡ Generate Offers (1-Shot)"}
          </button>
          <button
            className="btn btn-primary"
            onClick={handleNegotiate}
            disabled={generating}
            style={{ background: "var(--accent)" }}
          >
            {generating ? "Negotiating..." : "🔄 Live Negotiate"}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="skeleton-list">
          {[1, 2].map((i) => (
            <div key={i} className="skeleton" style={{ height: 120 }} />
          ))}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "24px", padding: "16px" }}>
          
          <div className="signals-panel" style={{ background: "var(--bg-input)", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ marginTop: 0, marginBottom: "16px" }}>Demand Signals</h3>
            <table className="table" style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
              <thead>
                <tr>
                  <th>Customer Email</th>
                  <th>Quantity</th>
                  <th>Status</th>
                  <th>Allocated?</th>
                  <th>Offer</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {signals.map(s => {
                  const isDemo = s.customer_email?.startsWith("demo.");
                  return (
                  <tr key={s.demand_signal_id} style={{ borderBottom: "1px solid var(--border)", opacity: isDemo ? 0.6 : 1 }}>
                    <td style={{ padding: "8px" }}>
                      {s.customer_email || "Unknown"}
                      {isDemo && <span style={{ marginLeft: 6, fontSize: 11, background: "#553", color: "#fff", padding: "2px 6px", borderRadius: 4 }}>DEMO</span>}
                    </td>
                    <td style={{ padding: "8px" }}>{s.quantity}</td>
                    <td style={{ padding: "8px" }}>{s.status}</td>
                    <td style={{ padding: "8px" }}>
                      {s.allocated ? "✅" : "❌"}
                    </td>
                    <td style={{ padding: "8px" }}>
                      {s.allocated && s.allocation?.offer ? (
                        `${s.allocation.offer.offer_type} — ₹${Number(s.allocation.offer.price).toLocaleString("en-IN")}`
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={{ padding: "8px" }}>
                      {s.allocated ? (
                        <button
                          className="btn"
                          style={{ fontSize: "0.8rem", padding: "4px 8px" }}
                          onClick={() => {
                            const link = `https://reclaim-t5ldhxld.myshopify.com/pages/special-offer?signal=${s.demand_signal_id}`;
                            navigator.clipboard.writeText(link);
                            alert("Copied to clipboard!");
                          }}
                        >
                          Copy Link
                        </button>
                      ) : "—"}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {generating && (
             <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 16px", background: "var(--bg-secondary)", borderRadius: "8px", border: "1px solid var(--border)" }}>
               <div className="spinner" style={{ width: 24, height: 24 }}></div>
               <div>
                 <strong style={{ display: "block" }}>🤖 Agents negotiating...</strong>
                 <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Analyzing value, price, and bundles across competing merchants.</span>
               </div>
             </div>
          )}

          {(negotiationRounds.length > 0 || generating) && (
            <div className="product-list" style={{ marginBottom: "24px" }}>
              <h3 style={{ marginTop: 0, padding: "0 16px" }}>Live Negotiation Feed</h3>
              {negotiationRounds.length === 0 && generating && <p style={{ padding: "0 16px", color: "var(--text-muted)", fontStyle: "italic" }}>Waiting for first round...</p>}
              <div style={{ padding: "0 16px", display: "flex", flexDirection: "column", gap: "12px" }}>
                {[...negotiationRounds]
                  .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
                  .map((r) => (
                  <div key={r.id} style={{ display: "flex", gap: 8, marginBottom: 6, padding: 8, background: r.revised_from_prior ? "#2a1f00" : "#1a1a1a", borderRadius: 6 }}>
                    <strong style={{ minWidth: 100 }}>{r.merchants?.name || r.merchant_id}</strong>
                    <span style={{ opacity: 0.6, fontSize: 12 }}>R{r.round_number}</span>
                    <span>{r.offer_type} @ ₹{Number(r.price).toLocaleString("en-IN")}</span>
                    {r.revised_from_prior && <span style={{ color: "orange" }}>↻ revised</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {offers.length === 0 && !generating ? (
            <div className="empty-state">
              <p>No offers yet. Trigger offer generation for this pool.</p>
            </div>
          ) : (
            <div className="product-list">
              <h3 style={{ marginTop: 0, padding: "0 16px" }}>Final Offers</h3>
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
                  <details style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
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
        </div>
      )}

      <div style={{ display: "flex", gap: 12, padding: "16px", borderTop: "1px solid var(--border)" }}>
        <button className="btn btn-primary" onClick={() => navigate(`/pools/${poolId}/marketplace`)}>
          View Marketplace →
        </button>
        <button className="btn" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)", border: "1px solid var(--border)" }} onClick={() => navigate("/")}>
          ← Back
        </button>
      </div>
    </div>
  );
}

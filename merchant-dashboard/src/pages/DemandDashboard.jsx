import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchDemandPools, fetchMultiProductPools, generateOffers, generateMultiProductOffers, API_BASE } from "../api";
import { supabase } from "../supabaseClient";
import { useDemoSession } from "../contexts/DemoSessionContext";

export default function DemandDashboard() {
  const [pools, setPools] = useState([]);
  const [multiPools, setMultiPools] = useState([]);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(null);
  const navigate = useNavigate();
  const { setPoolId, setDemandSignalId } = useDemoSession();

  const [showBulkSim, setShowBulkSim] = useState(false);
  const [bulkProductId, setBulkProductId] = useState("");
  const [bulkCount, setBulkCount] = useState(20);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkResult, setBulkResult] = useState(null);
  const [products, setProducts] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE}/products?limit=100`)
      .then(r => r.json())
      .then(setProducts);
  }, []);

  const handleSimulateBulk = async () => {
    if (!bulkProductId) return;
    setBulkLoading(true);
    setBulkResult(null);
    try {
      const res = await fetch(`${API_BASE}/demo/simulate-bulk-demand`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: bulkProductId, customer_count: Number(bulkCount) }),
      });
      const data = await res.json();
      setBulkResult(data);
      load(); // refresh the pool list so the new/updated pool shows immediately
    } catch (e) {
      setBulkResult({ error: e.message || "Failed to simulate demand" });
    } finally {
      setBulkLoading(false);
    }
  };

  const handleCleanupDemoData = async () => {
    if (!window.confirm("Delete all synthetic demo carts/signals? This cannot be undone.")) return;
    const res = await fetch(`${API_BASE}/demo/cleanup-bulk-demand`, { method: "DELETE" });
    const data = await res.json();
    alert(`Cleaned up ${data.deleted_count} demo carts`);
    load();
  };

  const load = async () => {
    try {
      setError("");
      const [data, multiData] = await Promise.all([
        fetchDemandPools(),
        fetchMultiProductPools()
      ]);
      setPools(data);
      setMultiPools(multiData);
    } catch (e) {
      setError(e.message || "Failed to load demand pools");
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!supabase) return;
    const channel = supabase
      .channel("demand_pools_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "demand_pools" },
        () => load()
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const handleGenerate = async (poolId, isMulti = false) => {
    setGenerating(poolId);
    setError("");
    try {
      if (isMulti) {
        const res = await generateMultiProductOffers(poolId);
        if (res.allocation_error) {
          setError(`Allocation error: ${res.allocation_error}`);
        } else {
          alert(`Bundle generation complete! Generated ${res.validated_offers} valid bundle offers from ${res.merchants_processed} merchants.`);
          load();
        }
      } else {
        const res = await generateOffers(poolId);
        if (res.failures > 0) {
          setError(
            `Offer generation completed with ${res.failures} failures. Details: ${JSON.stringify(
              res.failure_details
            )}`
          );
        }
        setPoolId(poolId);
        setDemandSignalId(null);
        navigate(`/pools/${poolId}/competition`);
      }
    } catch (e) {
      setError(e.message || "Failed to trigger offer generation");
    } finally {
      setGenerating(null);
    }
  };

  return (
    <div style={{ padding: 16, maxWidth: 900, margin: "0 auto" }}>
      <h2>Demand Dashboard</h2>
      <p style={{ opacity: 0.8 }}>
        Live updates when Supabase Realtime is enabled for demand_pools.
      </p>

      <div style={{ border: "1px dashed #888", borderRadius: 12, padding: 16, marginBottom: 20 }}>
        <button onClick={() => setShowBulkSim(!showBulkSim)} style={{ fontWeight: 600 }}>
          🧪 Simulate Bulk Demand (Demo)
        </button>
        <button onClick={handleCleanupDemoData} style={{ color: "crimson", marginLeft: 12 }}>
          🧹 Clean Up Demo Data
        </button>

        {showBulkSim && (
          <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <select value={bulkProductId} onChange={(e) => setBulkProductId(e.target.value)}>
              <option value="">Select a product...</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} — ₹{p.price}
                </option>
              ))}
            </select>

            <input
              type="number"
              min="1"
              max="200"
              value={bulkCount}
              onChange={(e) => setBulkCount(e.target.value)}
              style={{ width: 80 }}
            />
            <span>customers</span>

            <button onClick={handleSimulateBulk} disabled={bulkLoading || !bulkProductId}>
              {bulkLoading ? "Simulating..." : "Run Simulation"}
            </button>

            {bulkResult && !bulkResult.error && (
              <span style={{ color: "lightgreen" }}>
                ✅ Created {bulkResult.created_signals} signals for pool
              </span>
            )}
            {bulkResult?.error && (
              <span style={{ color: "crimson" }}>❌ {bulkResult.error}</span>
            )}
          </div>
        )}
      </div>

      {error && <div style={{ color: "crimson" }}>{error}</div>}

      <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
        {pools.map((p) => (
          <div
            key={p.id}
            style={{
              border: "1px solid #eee",
              borderRadius: 12,
              padding: 12,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: "8px" }}>
                {p.product_groups?.model_name || `Pool ${String(p.id).slice(0, 8)}`}
                {p.signals?.length > 0 && p.signals.every(s => s.customer_email?.startsWith("demo.")) && (
                  <span style={{ background: "#553", color: "#fff", padding: "2px 8px", borderRadius: 4, fontSize: 11 }}>DEMO POOL</span>
                )}
              </div>
              <div style={{ fontSize: 14, opacity: 0.8 }}>
                signals: {p.signal_count} · status: {p.status}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {p.status === "open" && (
                <button
                  className="btn"
                  onClick={() => navigate(`/pools/${p.id}/negotiation`)}
                >
                  🤝 Enter Negotiation Room
                </button>
              )}
              <button
                onClick={() => {
                  setPoolId(p.id);
                  setDemandSignalId(null);
                  navigate(`/pools/${p.id}/competition`);
                }}
              >
                View
              </button>
            </div>
          </div>
        ))}
      </div>

      <h3 style={{ marginTop: 40 }}>Multi-Product Cart Pools (Bundles)</h3>
      <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
        {multiPools.length === 0 && <p style={{ opacity: 0.6 }}>No multi-product pools found.</p>}
        {multiPools.map((p) => (
          <div
            key={p.id}
            style={{
              border: "1px solid #7c3aed",
              borderRadius: 12,
              padding: 12,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              background: "rgba(124, 58, 237, 0.05)"
            }}
          >
            <div>
              <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: "8px", color: "#7c3aed" }}>
                Basket: {p.basket_signature?.substring(0, 16)}...
              </div>
              <div style={{ fontSize: 14, opacity: 0.8 }}>
                customers: {p.cart_count} · items: {p.total_items} · status: <strong style={{color: p.status === 'open' ? '#3b82f6' : '#10b981'}}>{p.status}</strong>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {p.status === "open" && (
                <button
                  className="btn btn-primary"
                  style={{ background: "#7c3aed", borderColor: "#7c3aed" }}
                  onClick={() => navigate(`/pools/${p.id}/negotiation`)}
                >
                  🤝 Enter Negotiation Room
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


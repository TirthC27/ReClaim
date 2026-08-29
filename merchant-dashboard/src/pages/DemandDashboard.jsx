import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchDemandPools, generateOffers } from "../api";
import { supabase } from "../supabaseClient";
import { useDemoSession } from "../contexts/DemoSessionContext";

export default function DemandDashboard() {
  const [pools, setPools] = useState([]);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(null);
  const navigate = useNavigate();
  const { setPoolId, setDemandSignalId } = useDemoSession();

  const load = async () => {
    try {
      setError("");
      const data = await fetchDemandPools();
      setPools(data);
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

  const handleGenerate = async (poolId) => {
    setGenerating(poolId);
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
      setPoolId(poolId);
      setDemandSignalId(null);
      navigate(`/pools/${poolId}/competition`);
    } catch (e) {
      setError(e.message || "Failed to trigger offer generation");
      setGenerating(null);
    }
  };

  return (
    <div style={{ padding: 16, maxWidth: 900, margin: "0 auto" }}>
      <h2>Demand Dashboard</h2>
      <p style={{ opacity: 0.8 }}>
        Live updates when Supabase Realtime is enabled for demand_pools.
      </p>

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
              <div style={{ fontWeight: 600 }}>
                Pool {String(p.id).slice(0, 8)}
              </div>
              <div style={{ fontSize: 14, opacity: 0.8 }}>
                signals: {p.signal_count} · status: {p.status}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {p.status === "open" && (
                <button
                  className="btn btn-primary"
                  onClick={() => handleGenerate(p.id)}
                  disabled={generating === p.id}
                >
                  {generating === p.id ? "Evaluating..." : "⚡ Trigger Agents"}
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
    </div>
  );
}

